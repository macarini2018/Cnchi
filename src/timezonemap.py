#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
#  timezonemap.py
#
#  Portions from Ubiquity, Copyright (C) 2009 Canonical Ltd.
#  Written in C by Evan Dandrea <evand@ubuntu.com>
#  Python code Copyright © 2013,2014 Antergos
#
#  This file is part of Cnchi.
#
#  Cnchi is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.
#
#  Cnchi is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Cnchi; if not, write to the Free Software
#  Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#  MA 02110-1301, USA.

""" Custom widget to show world time zones """

from gi.repository import Gdk, Gtk, GdkPixbuf, cairo, Pango, PangoCairo

import canonical.tz as tz

import os
import math

# location-changed
# set_timezone
# get_timezone_at_coords

PIN_HOT_POINT_X = 8
PIN_HOT_POINT_Y = 15
LOCATION_CHANGED = 0

G_PI_4 = 0.78539816339744830961566084581987572104929234984378

TIMEZONEMAP_IMAGES_PATH = "/usr/share/cnchi/data/images/timezonemap"

def radians(degrees):
    return (degrees / 360.0) * math.pi * 2

class Timezonemap(Gtk.Widget):
    __gtype_name__ = 'Timezonemap'

    def __init__(self, *args, **kwds):
        super().__init__(*args, **kwds)
        self.set_size_request(40, 40)

        self._background = None
        self._color_map = None
        self._visible_map_pixels = None
        self._visible_map_rowstride = None
        self._selected_offset = 0
        self._location = None
        self._bubble_text = ""
  
        path = os.path.join(TIMEZONEMAP_IMAGES_PATH, "bg.png")
        self._orig_background = GdkPixbuf.Pixbuf.new_from_file(path)
        path = os.path.join(TIMEZONEMAP_IMAGES_PATH, "bg_dim.png")
        self._orig_background_dim = GdkPixbuf.Pixbuf.new_from_file(path)
        path = os.path.join(TIMEZONEMAP_IMAGES_PATH, "cc.png")
        self._orig_color_map = GdkPixbuf.Pixbuf.new_from_file(path)
        path = os.path.join(TIMEZONEMAP_IMAGES_PATH, "pin.png")
        self._pin = GdkPixbuf.Pixbuf.new_from_file(path)

        self._tzdb = tz.Database()

        self.connect("button-press-event", self.button_press_event)

    def do_get_preferred_width(self):
        return self.orig_background.get_width()
    
    def do_get_preferred_height(self):
        return self.orig_background.get_height()
    
    def do_size_allocate(self, allocation):
        if self._background:
            del self._background
            self._background = None
        
        if self.is_sensitive():
            pixbuf = self._orig_background
        else:
            pixbuf = self._orig_background_dim
        
        self._background = pixbuf.scale_simple(
            allocation.width,
            allocation.height,
            Gdk.INTERP_BILINEAR)
        
        if self._color_map:
            del self._color_map
            self._color_map = None
        
        self._color_map = self._orig_color_map.scale_simple(
            allocation.width,
            allocation.height,
            Gdk.INTERP_BILINEAR)
        
        self._visible_map_pixels = self._color_map.get_pixels()
        self._visible_map_rowstride = self._color_map.get_rowstride()

        super().size_allocate(allocation)

    '''
    def do_realize(self):
        allocation = self.get_allocation()
        attr = Gdk.WindowAttr()
        attr.window_type = Gdk.WindowType.CHILD
        attr.x = allocation.x
        attr.y = allocation.y
        attr.width = allocation.width
        attr.height = allocation.height
        attr.visual = self.get_visual()
        attr.event_mask = self.get_events() | Gdk.EventMask.EXPOSURE_MASK
        WAT = Gdk.WindowAttributesType
        mask = WAT.X | WAT.Y | WAT.VISUAL
        window = Gdk.Window(self.get_parent_window(), attr, mask);
        self.set_window(window)
        self.register_window(window)
        self.set_realized(True)
        window.set_background_pattern(None)
    '''

    def do_realize(self):
        allocation = self.get_allocation()
        self.set_realized(True)
        attr = Gdk.WindowAttr()
        attr.window_type = Gdk.WindowType.CHILD
        # GDK_INPUT_OUTPUT
        attr.wclass = Gdk.InputType.OUTPUT
        attr.width = allocation.width
        attr.height = allocation.height
        attr.x = allocation.x
        attr.y = allocation.y
        #attr.visual = self.get_visual()
        attr.event_mask = self.get_events() | Gdk.EventMask.EXPOSURE_MASK | Gdk.EventMask.BUTTON_PRESS_MASK
        wat = Gdk.WindowAttributesType
        mask = wat.X | wat.Y | wat.VISUAL
        window = Gdk.Window(self.get_parent_window(), attr, mask);
        #window.set_user_data(self)
        self.set_window(window)
        #self.register_window(window)
        #window.set_background_pattern(None)

    def convert_longitude_to_x(self, longitude, map_width):
        xdeg_offset = -6
        return (map_width * (180.0 + longitude) / 360.0) + (map_width * xdeg_offset / 180.0)
    
    def convert_latitude_to_y(self, latitude, map_height):
        bottom_lat = -59;
        top_lat = 81;

        top_per = top_lat / 180.0;
        y = 1.25 * math.log(math.tan(G_PI_4 + 0.4 * radians(latitude)))
        full_range = 4.6068250867599998
        top_offset = full_range * top_per
        map_range = math.fabs(1.25 * math.log(math.tan(G_PI_4 + 0.4 * radians(bottom_lat))) - top_offset)
        y = fabs (y - top_offset)
        y = y / map_range
        y = y * map_height
        return y

    # http://lotsofexpression.blogspot.com.es/2012/04/python-gtk-3-pango-cairo-example.html
    def draw_text_bubble(self, cr, pointx, pointy):
        corner_radius = 9.0
        margin_top = 12.0
        margin_bottom = 12.0
        margin_left = 24.0
        margin_right = 24.0
        
        if len(self._bubble_text) <= 0:
            return
        
        alloc = self.get_allocation()
        
        layout = self.create_pango_layout()
        
        layout.set_alignment(PANGO_ALIGN_CENTER)
        layout.set_spacing(3)
        layout.set_markup(self._bubble_text)
        text_rect = layout.get_pixel_extents()

        # Calculate the bubble size based on the text layout size
        width = text_rect.width + margin_left + margin_right
        height = text_rect.height + margin_top + margin_bottom
        
        if pointx < alloc.width / 2:
            x = pointx + 25
        else
            x = pointx - width - 25

        y = pointy - height / 2

        # Make sure it fits in the visible area
        x = CLAMP (x, 0, alloc.width - width)
        y = CLAMP (y, 0, alloc.height - height)
        
        cr.save()
        cr.translate(x, y)
        
        # Draw the bubble
        cr.new_sub_path()
        cr.arc(width - corner_radius, corner_radius, corner_radius, radians(-90), radians(0))
        cr.arc(width - corner_radius, height - corner_radius, corner_radius, radians(0), radians(90))
        cr.arc(corner_radius, height - corner_radius, corner_radius, radians(90), radians(180))
        cr.arc(corner_radius, corner_radius, corner_radius, radians(180), radians(270))
  
        cr.close_path()

        cr.set_source_rgba(0.2, 0.2, 0.2, 0.7)
        cr.fill()

        # And finally draw the text
        cr.set_source_rgb(1, 1, 1)
        cr.move_to(margin_left, margin_top)
        PangoCairo.show_layout (cr, layout);
        cr.restore()

    '''
    def do_draw(self, cr):
        # paint background
        bg_color = self.get_style_context().get_background_color(Gtk.StateFlags.NORMAL)
        cr.set_source_rgba(*list(bg_color))
        cr.paint()
        # draw a diagonal line
        allocation = self.get_allocation()
        fg_color = self.get_style_context().get_color(Gtk.StateFlags.NORMAL)
        cr.set_source_rgba(*list(fg_color));
        cr.set_line_width(2)
        cr.move_to(0, 0)   # top left of the widget
        cr.line_to(allocation.width, allocation.height)
        cr.stroke()
    '''

    def do_draw(self, cr):
        alloc = self.get_allocation()
        # Paint background
        bg_color = self.get_style_context().get_background_color(Gtk.StateFlags.NORMAL)
        cr.set_source_rgba(*list(bg_color))
        cr.paint()

        # Paint hilight
        if self.is_sensitive():
            filename = "timezone_%s.png" % str(self._selected_offset)
        else:
            filename = "timezone_%s_dim.png" % str(self._selected_offset)
        
        path = os.path.join(TIMEZONEMAP_IMAGES_PATH, filename)
  
        try:
            orig_hilight = GdkPixbuf.Pixbuf.new_from_file(path)
        except Exception as err:
            print("Can't load %s image file" % path)
            return

        hilight = orig_hilight.scale_simple(
            alloc.width,
            alloc.height,
            Gdk.INTERP_BILINEAR)

        cr.set_source_pixbuf(hilight, 0, 0)
        cr.paint()
        
        del hilight
        del orig_hilight

        '''
        if self._location:
  if (priv->location)
    {
      pointx = convert_longitude_to_x (priv->location->longitude, alloc.width);
      pointy = convert_latitude_to_y (priv->location->latitude, alloc.height);

      pointx = CLAMP (floor (pointx), 0, alloc.width);
      pointy = CLAMP (floor (pointy), 0, alloc.height);

      draw_text_bubble (cr, widget, pointx, pointy);

      if (priv->pin)
        {
          gdk_cairo_set_source_pixbuf (cr, priv->pin,
                                       pointx - PIN_HOT_POINT_X,
                                       pointy - PIN_HOT_POINT_Y);
          cairo_paint (cr);
        }
    }
        '''
  
  
        

if __name__ == '__main__':
    win = Gtk.Window()
    win.add(Timezonemap())
    win.show_all()
    win.present()
    import signal    # enable Ctrl-C since there is no menu to quit
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    Gtk.main()
