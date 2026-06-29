# entities.py  –  Layer, Character, and SceneMarker classes
import pygame
import math
import campaigns
from constants import *


class Layer:
    def __init__(self, img, speed=1.0):
        self.img   = img
        self.speed = speed
        self.x     = 0.0
        self.y     = 0.0

    def update(self, dx, dy):
        self.x -= dx * self.speed
        self.y -= dy * self.speed

    def clamp(self, w, h):
        iw, ih = self.img.get_size()
        self.x = max(min(0.0, self.x), float(w  - iw))
        self.y = max(min(0.0, self.y), float(h - ih))

    def draw(self, surface):
        surface.blit(self.img, (int(self.x), int(self.y)))


class Character:
    def __init__(self, x, y, color, size, name, id=None, is_enemy=False):
        self.id         = id
        self.x          = float(x)
        self.y          = float(y)
        self.color      = color
        self.size       = size
        self.name       = name
        self.is_enemy   = is_enemy
        self.selected   = False
        self.targeted   = False
        self.image      = None
        self.image_path = ''
        self.hp         = 10
        self.max_hp     = 10
        self.conditions = set()   # set of condition codes e.g. {'POI','PRN'}
        self.initiative = 0
        self.init_bonus = 0       # added to every initiative roll
        self.scene_id   = 0       # 0 = global (appears in all scenes)

    # ── Drawing ───────────────────────────────────────────────────────────────

    def draw(self, surface, camera_x, camera_y,
             current_turn=False, font=None, small_font=None):
        sx = int(self.x - camera_x)
        sy = int(self.y - camera_y)
        r  = self.size

        # Token body
        if self.image:
            img = pygame.transform.scale(self.image, (r * 2, r * 2))
            surface.blit(img, (sx - r, sy - r))
        else:
            pygame.draw.circle(surface, self.color, (sx, sy), r)

        # Condition swirl — color-cycling comet orbiting the token
        if self.conditions:
            ticks    = pygame.time.get_ticks()
            orb_r    = r + 14
            n_dots   = 8
            base_ang = (ticks / 1500.0) * math.tau
            base_hue = (ticks / 50.0) % 360.0
            ow       = (orb_r + 8) * 2
            overlay  = pygame.Surface((ow, ow), pygame.SRCALPHA)
            ocx      = ow // 2
            for i in range(n_dots):
                frac  = 1.0 - i / n_dots
                ang   = base_ang - i * (math.tau * 0.65 / n_dots)
                dot_x = ocx + int(orb_r * math.cos(ang))
                dot_y = ocx + int(orb_r * math.sin(ang))
                dot_r = max(2, int(6 * frac))
                alpha = int(220 * frac)
                hue   = (base_hue + i * 18) % 360.0
                c     = pygame.Color(0)
                c.hsva = (int(hue), 90, 100, 100)
                pygame.draw.circle(overlay, (c.r, c.g, c.b, alpha), (dot_x, dot_y), dot_r)
            surface.blit(overlay, (sx - ocx, sy - ocx))

        # Current-turn glow
        if current_turn:
            pygame.draw.circle(surface, WHITE, (sx, sy), r + 5, 3)

        # Selected ring (yellow)
        if self.selected:
            pygame.draw.circle(surface, YELLOW, (sx, sy), r + 2, 2)

        # Targeted crosshair (red)
        if self.targeted:
            arm = r + 10
            pygame.draw.line(surface, RED, (sx - arm, sy), (sx + arm, sy), 2)
            pygame.draw.line(surface, RED, (sx, sy - arm), (sx, sy + arm), 2)

        # HP bar (below token)
        bw = r * 2; bh = 6
        bx = sx - r; by = sy + r + 3
        pygame.draw.rect(surface, (100, 0, 0), (bx, by, bw, bh))
        if self.max_hp > 0:
            ratio = max(0.0, min(1.0, self.hp / self.max_hp))
            fw    = int(bw * ratio)
            col   = GREEN if ratio > 0.5 else (ORANGE if ratio > 0.25 else RED)
            if fw > 0:
                pygame.draw.rect(surface, col, (bx, by, fw, bh))

        # Name label (above token)
        if font:
            lbl = font.render(self.name, True, WHITE)
            surface.blit(lbl, (sx - lbl.get_width() // 2, sy - r - 20))

        # Condition chips (below HP bar)
        if self.conditions and small_font:
            chip = 12; gap = 1
            clist = sorted(self.conditions)
            total_w = len(clist) * (chip + gap) - gap
            cx = sx - total_w // 2
            cy = by + bh + 3
            for code in clist:
                info = CONDITIONS.get(code)
                if info:
                    lbl, col, _ = info
                    pygame.draw.rect(surface, col, (cx, cy, chip, chip))
                    t = small_font.render(lbl[0], True, BLACK)
                    surface.blit(t, (cx + 1, cy))
                    cx += chip + gap

    # ── Helpers ───────────────────────────────────────────────────────────────

    def is_clicked(self, pos, camera_x, camera_y):
        wx = pos[0] + camera_x
        wy = pos[1] + camera_y
        return (wx - self.x) ** 2 + (wy - self.y) ** 2 <= self.size ** 2

    def set_image(self, path):
        try:
            resolved = campaigns.resolve_image_path(path)
            self.image = pygame.image.load(resolved).convert_alpha()
        except (pygame.error, FileNotFoundError, OSError):
            print(f"Could not load image: {path}")
            self.image = None

    def conditions_str(self):
        return ','.join(sorted(self.conditions))

    def load_conditions(self, s):
        self.conditions = {c for c in s.split(',') if c} if s else set()

    def snap_to_grid(self, grid_size):
        self.x = round(self.x / grid_size) * grid_size
        self.y = round(self.y / grid_size) * grid_size


# ── Sound Zone ─────────────────────────────────────────────────────────────────

class SoundZone:
    """A rectangular area that triggers a music track when players enter."""

    def __init__(self, id, name, x, y, w, h, track, color_hex, scene_id=0):
        self.id        = id
        self.name      = name
        self.x         = float(x)
        self.y         = float(y)
        self.w         = float(w)
        self.h         = float(h)
        self.track     = track
        self.color_hex = color_hex
        self.scene_id  = scene_id
        self._rgb      = self._hex_to_rgb(color_hex)

    @staticmethod
    def _hex_to_rgb(h):
        h = h.lstrip('#')
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)

    def contains(self, px, py):
        return self.x <= px <= self.x + self.w and self.y <= py <= self.y + self.h

    def screen_rect(self, camera_x, camera_y, toolbar_h):
        return pygame.Rect(
            int(self.x - camera_x),
            int(self.y - camera_y) + toolbar_h,
            int(self.w),
            int(self.h),
        )

    def is_clicked(self, screen_pos, camera_x, camera_y, toolbar_h):
        return self.screen_rect(camera_x, camera_y, toolbar_h).collidepoint(screen_pos)

    def draw(self, surface, camera_x, camera_y, toolbar_h, font, active=False):
        r, g, b = self._rgb
        rect = self.screen_rect(camera_x, camera_y, toolbar_h)

        # Semi-transparent fill
        overlay = pygame.Surface((max(1, rect.w), max(1, rect.h)), pygame.SRCALPHA)
        overlay.fill((r, g, b, 55 if active else 28))
        surface.blit(overlay, (rect.x, rect.y))

        # Border (brighter/thicker when active)
        pygame.draw.rect(surface, (r, g, b) if not active else (255, 255, 160),
                         rect, 3 if active else 2)

        # Note icon + name label
        if font and rect.w > 30 and rect.h > 16:
            lbl = font.render(f'♫ {self.name}', True, (r, g, b))
            surface.blit(lbl, (rect.centerx - lbl.get_width() // 2,
                               rect.centery - lbl.get_height() // 2))


# ── Scene Marker ───────────────────────────────────────────────────────────────

class SceneMarker:
    R = 22   # icon radius

    def __init__(self, id, wx, wy, to_scene_id, to_scene_name):
        self.id           = id
        self.x            = float(wx)
        self.y            = float(wy)
        self.to_scene_id  = to_scene_id
        self.to_scene_name = to_scene_name

    def screen_xy(self, camera_x, camera_y, toolbar_h):
        return (int(self.x - camera_x), int(self.y - camera_y) + toolbar_h)

    def is_clicked(self, screen_pos, camera_x, camera_y, toolbar_h):
        sx, sy = self.screen_xy(camera_x, camera_y, toolbar_h)
        return math.hypot(screen_pos[0] - sx, screen_pos[1] - sy) <= self.R + 4

    def draw(self, surface, camera_x, camera_y, toolbar_h, font):
        sx, sy = self.screen_xy(camera_x, camera_y, toolbar_h)
        r = self.R
        temporary = (self.id is None)

        if temporary:
            # Amber/gold return portal
            pygame.draw.circle(surface, (80, 50, 0),   (sx, sy), r + 4)
            pygame.draw.circle(surface, (210, 150, 20), (sx, sy), r)
            # Dashed inner ring (8 dots around the inner radius)
            for i in range(8):
                a = math.radians(i * 45)
                dx, dy = int(math.cos(a) * (r - 7)), int(math.sin(a) * (r - 7))
                pygame.draw.circle(surface, (255, 220, 120), (sx + dx, sy + dy), 2)
            # Back-arrow chevron pointing left
            pts = [
                (sx + 6, sy - 8),
                (sx - 6, sy),
                (sx + 6, sy + 8),
            ]
            pygame.draw.lines(surface, (60, 30, 0), False, pts, 3)
            lbl_col = (255, 230, 160)
            bg_col  = (60, 40, 0)
        else:
            # Teal permanent portal
            pygame.draw.circle(surface, (0, 60, 70),   (sx, sy), r + 4)
            pygame.draw.circle(surface, (0, 195, 180), (sx, sy), r)
            pygame.draw.circle(surface, (180, 255, 245), (sx, sy), r - 7, 2)
            # Forward chevron pointing right
            pts = [
                (sx - 6, sy - 8),
                (sx + 6, sy),
                (sx - 6, sy + 8),
            ]
            pygame.draw.lines(surface, (0, 30, 40), False, pts, 3)
            lbl_col = (220, 255, 250)
            bg_col  = (0, 40, 50)

        lbl = font.render(self.to_scene_name, True, lbl_col)
        bg_r = pygame.Rect(sx - lbl.get_width() // 2 - 3,
                           sy + r + 2,
                           lbl.get_width() + 6,
                           lbl.get_height() + 2)
        pygame.draw.rect(surface, bg_col, bg_r, border_radius=3)
        surface.blit(lbl, (bg_r.x + 3, bg_r.y + 1))
