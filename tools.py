# tools.py  –  FogOfWar, AoeTool, MeasureTool
import pygame
import math
from constants import *


# ── Fog of War ────────────────────────────────────────────────────────────────

class FogOfWar:
    def __init__(self):
        self.edit = False  # True when fog is active

    def draw(self, surface, camera_x, camera_y, screen_w, screen_h, toolbar_h,
             vision_sources=None, vision_radius=None):
        """
        Draw a black fog layer with holes where cells are revealed.
        vision_sources: list of (world_x, world_y) for player characters.
        vision_radius: bright-zone radius in px (defaults to VISION_RADIUS_PX).
        """
        # Build fog surface the size of the visible area
        view_h = screen_h - toolbar_h
        fog = pygame.Surface((screen_w, view_h), pygame.SRCALPHA)
        fog.fill((0, 0, 0, 252))   # 99% opaque black

        # Cut vision circles around player characters
        if vision_sources:
            r_bright = vision_radius if vision_radius is not None else VISION_RADIUS_PX
            r_dim    = r_bright + VISION_DIM_PX
            for wx, wy in vision_sources:
                sx = int(wx - camera_x)
                sy = int(wy - camera_y)
                pygame.draw.circle(fog, (0, 0, 0, 150), (sx, sy), r_dim)
            for wx, wy in vision_sources:
                sx = int(wx - camera_x)
                sy = int(wy - camera_y)
                pygame.draw.circle(fog, (0, 0, 0, 0), (sx, sy), r_bright)

        surface.blit(fog, (0, toolbar_h))


# ── AoE Tool ──────────────────────────────────────────────────────────────────

_AOE_COLORS = {
    'circle': (255, 100,   0, 90),
    'cone':   (200,   0, 200, 90),
    'line':   ( 50, 150, 255, 90),
}

class PlacedTemplate:
    def __init__(self, shape, wx, wy, wx2=None, wy2=None, radius=None):
        self.shape  = shape    # 'circle' | 'cone' | 'line'
        self.wx     = wx       # world origin x
        self.wy     = wy       # world origin y
        self.wx2    = wx2      # world end x (for cone/line)
        self.wy2    = wy2      # world end y (for cone/line)
        self.radius = radius   # for circle


class AoeTool:
    """
    Drag to place an AoE template on the map.
    Placed templates persist until explicitly cleared.
    """

    def __init__(self):
        self.mode      = None   # 'circle' | 'cone' | 'line'
        self.placing   = False
        self.origin    = None   # (wx, wy)
        self.current   = None   # (wx, wy) live drag end
        self.templates = []     # list of PlacedTemplate

    # ── Drag lifecycle ────────────────────────────────────────────────────────

    def start(self, wx, wy):
        self.placing = True
        self.origin  = (wx, wy)
        self.current = (wx, wy)

    def update(self, wx, wy):
        self.current = (wx, wy)

    def place(self):
        """Commit the current drag as a placed template."""
        if not self.placing or self.origin is None:
            return
        ox, oy = self.origin
        cx, cy = self.current
        if self.mode == 'circle':
            r = math.hypot(cx - ox, cy - oy)
            self.templates.append(PlacedTemplate('circle', ox, oy, radius=r))
        elif self.mode in ('cone', 'line'):
            self.templates.append(PlacedTemplate(self.mode, ox, oy, cx, cy))
        self.placing = False
        self.origin  = None
        self.current = None

    def cancel(self):
        self.placing = False
        self.origin  = None
        self.current = None

    def clear_all(self):
        self.templates.clear()

    # ── Drawing ───────────────────────────────────────────────────────────────

    def draw(self, surface, camera_x, camera_y, toolbar_h):
        # Draw placed templates
        for t in self.templates:
            self._draw_template(surface, t, camera_x, camera_y, toolbar_h, alpha=140)

        # Draw live preview
        if self.placing and self.origin and self.current and self.mode:
            ox, oy = self.origin
            cx, cy = self.current
            preview = PlacedTemplate(self.mode, ox, oy, cx, cy,
                                     radius=math.hypot(cx-ox, cy-oy))
            self._draw_template(surface, preview, camera_x, camera_y, toolbar_h, alpha=90)

    def _draw_template(self, surface, t, camera_x, camera_y, toolbar_h, alpha):
        col = list(_AOE_COLORS.get(t.shape, (255,255,0,90)))
        col[3] = alpha
        sx = int(t.wx - camera_x)
        sy = int(t.wy - camera_y) + toolbar_h

        overlay = pygame.Surface(surface.get_size(), pygame.SRCALPHA)

        if t.shape == 'circle' and t.radius:
            pygame.draw.circle(overlay, col, (sx, sy), max(1, int(t.radius)))

        elif t.shape == 'line' and t.wx2 is not None:
            ex = int(t.wx2 - camera_x)
            ey = int(t.wy2 - camera_y) + toolbar_h
            pygame.draw.line(overlay, col, (sx, sy), (ex, ey), 10)

        elif t.shape == 'cone' and t.wx2 is not None:
            ex = int(t.wx2 - camera_x)
            ey = int(t.wy2 - camera_y) + toolbar_h
            length = math.hypot(ex - sx, ey - sy)
            if length > 0:
                angle  = math.atan2(ey - sy, ex - sx)
                half   = math.radians(26.5)   # ~53° cone
                lx = int(sx + length * math.cos(angle - half))
                ly = int(sy + length * math.sin(angle - half))
                rx = int(sx + length * math.cos(angle + half))
                ry = int(sy + length * math.sin(angle + half))
                pygame.draw.polygon(overlay, col, [(sx, sy), (lx, ly), (ex, ey), (rx, ry)])

        surface.blit(overlay, (0, 0))


# ── Measure Tool ──────────────────────────────────────────────────────────────

class MeasureTool:
    """Click two points to display the distance in feet."""

    def __init__(self):
        self.active = False
        self.start  = None   # (wx, wy)
        self.end    = None   # (wx, wy)

    def set_start(self, wx, wy):
        self.start = (wx, wy)
        self.end   = None

    def set_end(self, wx, wy):
        self.end = (wx, wy)

    def clear(self):
        self.start = None
        self.end   = None

    def distance_feet(self):
        if self.start and self.end:
            dx = self.end[0] - self.start[0]
            dy = self.end[1] - self.start[1]
            px = math.hypot(dx, dy)
            return px / GRID_SIZE * FEET_PER_CELL
        return None

    def draw(self, surface, camera_x, camera_y, toolbar_h, font):
        if not self.start:
            return
        sx = int(self.start[0] - camera_x)
        sy = int(self.start[1] - camera_y) + toolbar_h
        pygame.draw.circle(surface, TEAL, (sx, sy), 6)

        if self.end:
            ex = int(self.end[0] - camera_x)
            ey = int(self.end[1] - camera_y) + toolbar_h
            pygame.draw.circle(surface, TEAL, (ex, ey), 6)
            pygame.draw.line(surface, TEAL, (sx, sy), (ex, ey), 2)

            dist = self.distance_feet()
            label = font.render(f"{dist:.0f} ft", True, TEAL)
            mx = (sx + ex) // 2
            my = (sy + ey) // 2
            pygame.draw.rect(surface, DARK_GRAY,
                             (mx - 2, my - 2,
                              label.get_width() + 4, label.get_height() + 4))
            surface.blit(label, (mx, my))
