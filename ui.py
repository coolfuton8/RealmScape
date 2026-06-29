# ui.py  –  Toolbar, ContextMenu, InitiativePanel, HPPopup, ConditionsPopup
import pygame
import subprocess as _subprocess
from constants import *


def _read_clipboard() -> str:
    """Return clipboard text, trying multiple methods for Linux compatibility."""
    # tkinter is the most reliable cross-platform approach
    try:
        import tkinter as _tk
        _root = _tk.Tk()
        _root.withdraw()
        text = _root.clipboard_get()
        _root.destroy()
        if text:
            return text
    except Exception:
        pass
    # xdotool fallback
    try:
        r = _subprocess.run(['xdotool', 'getclipboard'],
                            capture_output=True, text=True, timeout=1)
        if r.returncode == 0:
            return r.stdout
    except Exception:
        pass
    # xclip / xsel fallback
    for cmd in (['xclip', '-selection', 'clipboard', '-o'],
                ['xsel', '--clipboard', '--output']):
        try:
            r = _subprocess.run(cmd, capture_output=True, text=True, timeout=1)
            if r.returncode == 0:
                return r.stdout
        except Exception:
            pass
    try:
        return pygame.scrap.get_text() or ''
    except Exception:
        return ''


# ── Toolbar ───────────────────────────────────────────────────────────────────

class Toolbar:
    """
    Grouped toolbar: coloured category tabs on the left open drop-down panels;
    turn tracker in the centre; scene controls on the right.
    """
    H = TOOLBAR_HEIGHT  # 64 px

    # (group_id, label, colour, [(btn_id, label, is_toggle)])
    _GROUPS = [
        ('campaign', 'Campaign', (80, 50, 120), [
            ('campaign_mgr',    'Manage Campaigns', False),
            ('open_manual',     'User Manual',      False),
            ('reset_campaign',  'Reset Campaign',   False),
            ('lock',            'Lock',             False),
            ('setup_pin',       'Set PIN',          False),
        ]),
        ('combat', 'Combat', (130, 45, 45), [
            ('add_enemy',  '+Enemy',     False),
            ('add_char',   '+Char',      False),
            ('roll_init',  'Roll Initiative', False),
            ('clear_all',  'Clear X',   False),
        ]),
        ('map', 'Map', (45, 115, 65), [
            ('grid_snap',       'Snap',              True),
            ('group_move',      'Group Move',        True),
            ('_zoom_slider',    '',                  False),
            ('set_start',       'Set As Starting Scene', False),
            ('undo',            'Undo',              False),
            ('party_home',      'Party Home',        False),
            ('scene_snapshot',  'Set Initial State', False),
            ('scene_revert',    'Revert Scene',      False),
        ]),
        ('fog', 'Fog', (45, 85, 150), [
            ('fog_on',  'Fog On',  True),
            ('fog_r15', '15 ft',   True),
            ('fog_r30', '30 ft',   True),
            ('fog_r45', '45 ft',   True),
            ('fog_r60', '60 ft',   True),
        ]),
        ('aoe', 'AoE', (150, 90, 25), [
            ('aoe_circle', 'Circle',     True),
            ('aoe_cone',   'Cone',       True),
            ('aoe_line',   'Line',       True),
            ('measure',    'Meas',       True),
        ]),
        ('view', 'View', (75, 75, 150), [
            ('show_init',  'Initiative', True),
            ('notes',      'Notes',      True),
            ('build_mode', 'Build Mode', True),
            ('show_grid',  'Grid',       True),
        ]),
        ('sound', 'Sound', (40, 100, 140), [
            ('music_enabled', 'Music On',      True),
            ('add_zone',      'Add Zone',      False),
            ('show_zones',    'Show Zones',    True),
            ('default_track', 'Default Track', False),
        ]),
    ]

    _T_PAD    = 4    # gap between group tabs
    _T_IP     = 14   # inner horizontal padding for tab labels
    _DD_BH    = 50   # dropdown button height
    _DD_IP    = 14   # inner horizontal padding for dropdown button labels
    _DD_GP    = 4    # gap between dropdown buttons
    _DD_VP    = 6    # top/bottom padding inside dropdown panel
    _ICON_W   = 32   # fixed width for generic icon decorators
    _SLIDER_W = 190  # fixed width for the zoom slider decorator
    _ZOOM_MIN = 0.1
    _ZOOM_MAX = 5.0

    def __init__(self, font):
        self.font         = font
        self._name_font   = pygame.font.Font(None, 17)  # smaller font for current-turn name
        self.active       = {'fog_on': True, 'fog_r30': True}
        self.disabled_btns = set()   # button ids that are greyed-out and non-interactive
        self.open_group   = None
        self._ck          = None   # cache key (screen_w, scene_name, open_group)
        self._tab_r       = {}
        self._sub_r       = {}
        self._drop_r      = None
        self._tp          = None   # turn-prev rect
        self._tl          = None   # turn-label rect
        self._tn          = None   # turn-next rect
        self._sc_r        = {}     # scene control rects
        # Zoom slider state
        self.zoom_level      = 1.0    # kept in sync with main.py current_zoom
        self._zoom_track_r   = None   # track rect used for hit-testing and drawing
        self._zoom_dragging  = False

    # ── Layout ────────────────────────────────────────────────────────────────

    def _layout(self, screen_w, scene_name):
        ck = (screen_w, scene_name, self.open_group)
        if ck == self._ck:
            return
        self._ck = ck
        H = self.H; P = self._T_PAD; IP = self._T_IP
        bh = H - 8   # button height inside the bar

        # Group tabs — left side
        x = P
        self._tab_r = {}
        for gid, label, _, _ in self._GROUPS:
            w = self.font.size(label)[0] + IP
            self._tab_r[gid] = pygame.Rect(x, 4, w, bh)
            x += w + P
        self._tabs_right = x

        # Scene controls — right side
        sc = {}; rx = screen_w - P
        for sid, w in [('del', 34), ('add', 34), ('next', 36)]:
            rx -= w; sc[sid] = pygame.Rect(rx, 4, w, bh); rx -= P
        sn   = scene_name or 'No Scene'
        sn_w = max(80, self.font.size(sn)[0] + 16)
        rx -= sn_w; sc['name'] = pygame.Rect(rx, 4, sn_w, bh); rx -= P
        rx -= 36;   sc['prev'] = pygame.Rect(rx, 4,    36, bh)
        self._sc_r       = sc
        self._scene_left = rx - P

        # Turn tracker — centred in remaining gap
        mid      = (self._tabs_right + self._scene_left) // 2
        self._tp = pygame.Rect(mid - 110, 4,  44, bh)
        self._tl = pygame.Rect(mid -  62, 4, 124, bh)
        self._tn = pygame.Rect(mid +  66, 4,  44, bh)

        # Dropdown for the open group
        self._drop_r = None; self._sub_r = {}
        if self.open_group:
            grp = next((g for g in self._GROUPS if g[0] == self.open_group), None)
            if grp:
                _, _, _, btns = grp
                tab_r = self._tab_r[self.open_group]
                bx    = tab_r.left
                dw    = self._DD_VP
                for bid, blbl, _ in btns:
                    dw += self._dec_w(bid, blbl) + self._DD_GP
                dw = max(dw, tab_r.width)
                bx = min(bx, max(P, screen_w - dw - P))
                self._drop_r = pygame.Rect(bx, H, dw, self._DD_BH + 2 * self._DD_VP)
                cx = bx + self._DD_VP
                self._zoom_track_r = None
                for bid, blbl, _ in btns:
                    bw = self._dec_w(bid, blbl)
                    r  = pygame.Rect(cx, H + self._DD_VP, bw, self._DD_BH)
                    self._sub_r[bid] = r
                    if bid == '_zoom_slider':
                        # Track rect: centred vertically, leaving room for icon and label
                        icon_w, label_w, pad = 28, 38, 6
                        tx = cx + icon_w + pad
                        tw = bw - icon_w - label_w - pad * 2
                        ty = H + self._DD_VP + self._DD_BH // 2 - 4
                        self._zoom_track_r = pygame.Rect(tx, ty, tw, 8)
                    cx += bw + self._DD_GP

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _dec_w(self, bid, blbl):
        """Width for a button or decorator entry."""
        if not bid.startswith('_'):
            return self.font.size(blbl)[0] + self._DD_IP
        if bid == '_zoom_slider':
            return self._SLIDER_W
        return self._ICON_W

    def _zoom_from_x(self, x):
        """Convert a screen x position to a clamped zoom value."""
        if self._zoom_track_r is None:
            return self.zoom_level
        tr = self._zoom_track_r
        frac = max(0.0, min(1.0, (x - tr.left) / tr.width))
        return round(self._ZOOM_MIN + frac * (self._ZOOM_MAX - self._ZOOM_MIN), 2)

    def handle_motion(self, pos):
        """Call on MOUSEMOTION. Returns new zoom float while dragging, else None."""
        if not self._zoom_dragging:
            return None
        self.zoom_level = self._zoom_from_x(pos[0])
        return self.zoom_level

    def handle_up(self):
        """Call on MOUSEBUTTONUP to end a slider drag."""
        self._zoom_dragging = False

    def _is_toggle(self, btn_id):
        for _, _, _, btns in self._GROUPS:
            for bid, _, is_tog in btns:
                if bid == btn_id:
                    return is_tog
        return False

    def _group_has_active(self, gid):
        for g_id, _, _, btns in self._GROUPS:
            if g_id == gid:
                return any(self.active.get(bid, False)
                           for bid, _, is_tog in btns if is_tog)
        return False

    # ── Public interface ──────────────────────────────────────────────────────

    def is_over(self, pos):
        return (pos[1] < self.H or
                (self._drop_r is not None and self._drop_r.collidepoint(pos)))

    def maybe_close_dropdown(self, pos):
        """Close the open dropdown if the click lands outside the toolbar area."""
        if not self.is_over(pos):
            self.open_group = None
            self._ck = None

    def click(self, pos):
        """Handle a click. Returns btn_id for actions/toggles, None for tab-clicks."""
        # Group tabs
        for gid, rect in self._tab_r.items():
            if rect.collidepoint(pos):
                self.open_group = gid if self.open_group != gid else None
                self._ck = None
                return None

        # Dropdown sub-buttons
        for bid, rect in self._sub_r.items():
            if rect.collidepoint(pos):
                if bid == '_zoom_slider':
                    # Expand hit area vertically so the narrow track is easy to grab
                    hit_r = self._zoom_track_r.inflate(0, 28) if self._zoom_track_r else rect
                    if hit_r.collidepoint(pos):
                        self._zoom_dragging = True
                        self.zoom_level = self._zoom_from_x(pos[0])
                        return '_zoom_slider'
                    return None
                if bid.startswith('_'):
                    return None   # other non-interactive decorators
                if bid in self.disabled_btns:
                    return None
                if self._is_toggle(bid):
                    self.active[bid] = not self.active.get(bid, False)
                    if bid in ('aoe_circle', 'aoe_cone', 'aoe_line'):
                        for other in ('aoe_circle', 'aoe_cone', 'aoe_line'):
                            if other != bid:
                                self.active[other] = False
                    _FOG_R = ('fog_r15', 'fog_r30', 'fog_r45', 'fog_r60')
                    if bid in _FOG_R:
                        for other in _FOG_R:
                            if other != bid:
                                self.active[other] = False
                else:
                    self.open_group = None   # close after action button
                    self._ck = None
                return bid

        # Click inside dropdown background (between buttons) → close
        if self._drop_r and self._drop_r.collidepoint(pos):
            self.open_group = None
            self._ck = None
            return None

        # Turn tracker
        if self._tp and self._tp.collidepoint(pos): return 'prev_turn'
        if self._tn and self._tn.collidepoint(pos): return 'next_turn'

        # Scene controls
        for key, bid in [('prev', 'scene_prev'), ('next', 'scene_next'),
                          ('add',  'scene_add'),  ('del',  'scene_del')]:
            r = self._sc_r.get(key)
            if r and r.collidepoint(pos):
                return bid
        r = self._sc_r.get('name')
        if r and r.collidepoint(pos):
            return 'scene_rename'
        return None

    def get_aoe_mode(self):
        for mode in ('circle', 'cone', 'line'):
            if self.active.get(f'aoe_{mode}'):
                return mode
        return None

    # ── Drawing ───────────────────────────────────────────────────────────────

    def _draw_icon(self, surface, bid, r):
        """Draw a non-interactive decorator icon inside rect r."""
        if bid == '_zoom_slider':
            col_muted  = (140, 145, 165)
            col_fill   = (85, 105, 190)
            col_thumb  = (130, 150, 230)
            col_track  = (55, 60, 80)

            # Magnifying glass (left side)
            icx = r.left + 16
            icy = r.centery
            rad = 7
            pygame.draw.circle(surface, col_muted, (icx, icy), rad, 2)
            hx = icx + int(rad * 0.65)
            hy = icy + int(rad * 0.65)
            pygame.draw.line(surface, col_muted, (hx, hy), (hx + 5, hy + 5), 3)

            # Slider track
            tr = self._zoom_track_r
            if tr:
                pygame.draw.rect(surface, col_track, tr, border_radius=4)
                frac = (self.zoom_level - self._ZOOM_MIN) / (self._ZOOM_MAX - self._ZOOM_MIN)
                fill_w = int(frac * tr.width)
                if fill_w > 0:
                    pygame.draw.rect(surface, col_fill,
                                     pygame.Rect(tr.left, tr.top, fill_w, tr.height),
                                     border_radius=4)
                thumb_x = max(tr.left + 6, min(tr.right - 6, tr.left + fill_w))
                pygame.draw.circle(surface, col_thumb, (thumb_x, tr.centery), 7)

            # Zoom label (right side)
            label = f'{self.zoom_level:.1f}×'
            lt = self.font.render(label, True, col_muted)
            surface.blit(lt, (r.right - 36, r.centery - lt.get_height() // 2))

    def draw(self, surface, screen_w, scene_name='—',
             turn_idx=0, turn_total=0, turn_name=''):
        self._layout(screen_w, scene_name)
        H = self.H

        # Bar background
        pygame.draw.rect(surface, TOOLBAR_BG, (0, 0, screen_w, H))
        pygame.draw.line(surface, PANEL_BORDER, (0, H - 1), (screen_w, H - 1))

        # Group tabs
        for gid, label, col, _ in self._GROUPS:
            r = self._tab_r.get(gid)
            if not r:
                continue
            is_open = (self.open_group == gid)
            bg = tuple(min(c + 45, 255) for c in col) if is_open else col
            pygame.draw.rect(surface, bg, r, border_radius=6)
            if self._group_has_active(gid) and not is_open:
                # Small green dot when group has an active toggle but panel is closed
                pygame.draw.circle(surface, (90, 230, 90),
                                   (r.right - 6, r.top + 6), 4)
            t = self.font.render(label, True, WHITE)
            surface.blit(t, (r.centerx - t.get_width() // 2,
                             r.centery - t.get_height() // 2))

        # Turn tracker
        for r, lbl in [(self._tp, '<'), (self._tn, '>')]:
            if r:
                pygame.draw.rect(surface, TOOLBAR_BTN, r, border_radius=5)
                t = self.font.render(lbl, True, WHITE)
                surface.blit(t, (r.centerx - t.get_width() // 2,
                                 r.centery - t.get_height() // 2))
        if self._tl:
            counter_txt = f'{turn_idx + 1} / {turn_total}' if turn_total else '- / -'
            c_surf = self.font.render(counter_txt, True, LIGHT_GRAY)
            if turn_name and turn_total:
                # Name capped to fit the label rect width
                nm = turn_name
                n_surf = self._name_font.render(nm, True, WHITE)
                while n_surf.get_width() > self._tl.width - 4 and len(nm) > 3:
                    nm = nm[:-1]
                    n_surf = self._name_font.render(nm + '...', True, WHITE)
                gap = 9  # px between name-bottom/Turn-top and counter edges
                cy = self._tl.centery - c_surf.get_height() // 2
                ny = cy - gap - n_surf.get_height()
                t_surf = self._name_font.render('Your Turn', True, LIGHT_GRAY)
                ty = cy + c_surf.get_height() + gap
                surface.blit(n_surf,  (self._tl.centerx - n_surf.get_width()  // 2, ny))
                surface.blit(c_surf,  (self._tl.centerx - c_surf.get_width()  // 2, cy))
                surface.blit(t_surf,  (self._tl.centerx - t_surf.get_width()  // 2, ty))
            else:
                surface.blit(c_surf, (self._tl.centerx - c_surf.get_width() // 2,
                                      self._tl.centery - c_surf.get_height() // 2))

        # Scene controls
        for key, lbl in [('prev', '<'), ('next', '>'),
                          ('add',  '+'), ('del',  '-')]:
            r = self._sc_r.get(key)
            if r:
                pygame.draw.rect(surface, TOOLBAR_BTN, r, border_radius=4)
                t = self.font.render(lbl, True, WHITE)
                surface.blit(t, (r.centerx - t.get_width() // 2,
                                 r.centery - t.get_height() // 2))
        r = self._sc_r.get('name')
        if r:
            pygame.draw.rect(surface, (45, 45, 58), r, border_radius=4)
            sn = scene_name or 'No Scene'
            t  = self.font.render(sn, True, LIGHT_GRAY)
            while t.get_width() > r.width - 8 and len(sn) > 3:
                sn = sn[:-1]
                t  = self.font.render(sn + '...', True, LIGHT_GRAY)
            surface.blit(t, (r.centerx - t.get_width() // 2,
                             r.centery - t.get_height() // 2))

        # Dropdown panel
        if self.open_group and self._drop_r:
            grp = next((g for g in self._GROUPS if g[0] == self.open_group), None)
            if grp:
                _, _, hdr_col, btns = grp
                dr = self._drop_r
                pygame.draw.rect(surface, TOOLBAR_BG, dr, border_radius=6)
                # Coloured accent strip at the very top edge
                pygame.draw.rect(surface, hdr_col,
                                 pygame.Rect(dr.left, dr.top, dr.width, 5))
                pygame.draw.rect(surface, PANEL_BORDER, dr, 1, border_radius=6)
                for bid, blbl, is_tog in btns:
                    r = self._sub_r.get(bid)
                    if not r:
                        continue
                    if bid.startswith('_'):
                        self._draw_icon(surface, bid, r)
                        continue
                    disabled = bid in self.disabled_btns
                    is_act   = is_tog and self.active.get(bid, False) and not disabled
                    btn_col  = (38, 38, 42) if disabled else (TOOLBAR_BTN_ACTIVE if is_act else TOOLBAR_BTN)
                    txt_col  = (75, 75, 82) if disabled else WHITE
                    pygame.draw.rect(surface, btn_col, r, border_radius=5)
                    t = self.font.render(blbl, True, txt_col)
                    surface.blit(t, (r.centerx - t.get_width() // 2,
                                     r.centery - t.get_height() // 2))


# ── Context menu ──────────────────────────────────────────────────────────────

class ContextMenu:
    """Pop-up list of actions at a screen position."""

    ITEM_H  = 44
    MIN_W   = 180
    PAD_X   = 24   # horizontal padding on each side of label text

    def __init__(self, pos, items, font):
        """
        items: list of (id, label) pairs.
               Use (None, '---') for a visual divider.
        """
        self.font  = font
        self.items = items
        self.rects = []
        x, y = pos
        max_text_w = max(
            (font.size(label)[0] for _, label in items if label != '---'),
            default=0,
        )
        self.WIDTH = max(self.MIN_W, max_text_w + self.PAD_X * 2)
        self.x = x
        self.y = y
        self._build(x, y)

    def _build(self, x, y):
        self.rects = []
        cy = y
        for item_id, label in self.items:
            if item_id is None:
                self.rects.append((None, pygame.Rect(x, cy, self.WIDTH, 4)))
                cy += 4
            else:
                self.rects.append((item_id, pygame.Rect(x, cy, self.WIDTH, self.ITEM_H)))
                cy += self.ITEM_H
        self.total_h = cy - y

    def reposition(self, screen_w, screen_h):
        """Nudge so menu stays on screen."""
        if self.x + self.WIDTH > screen_w:
            self.x = screen_w - self.WIDTH - 4
        if self.y + self.total_h > screen_h:
            self.y = screen_h - self.total_h - 4
        self._build(self.x, self.y)

    def draw(self, surface):
        for item_id, rect in self.rects:
            if item_id is None:
                pygame.draw.rect(surface, PANEL_BORDER, rect)
            else:
                pygame.draw.rect(surface, PANEL_BG, rect)
                pygame.draw.rect(surface, PANEL_BORDER, rect, 1)
                lbl = self.font.render(item_id.split('|')[1] if '|' in item_id else
                                       dict(self.items).get(item_id, item_id), True, WHITE)
                surface.blit(lbl, (rect.x + 10, rect.centery - lbl.get_height() // 2))

    def draw_labeled(self, surface):
        """Draw using the label string from items."""
        id_to_label = {i: l for i, l in self.items if i is not None}
        for item_id, rect in self.rects:
            if item_id is None:
                pygame.draw.rect(surface, PANEL_BORDER, rect)
            else:
                pygame.draw.rect(surface, PANEL_BG, rect)
                pygame.draw.rect(surface, PANEL_BORDER, rect, 1)
                lbl = self.font.render(id_to_label.get(item_id, item_id), True, WHITE)
                surface.blit(lbl, (rect.x + 10, rect.centery - lbl.get_height() // 2))

    def hit(self, pos):
        for item_id, rect in self.rects:
            if item_id is not None and rect.collidepoint(pos):
                return item_id
        return None

    def is_outside(self, pos):
        full = pygame.Rect(self.x, self.y, self.WIDTH, self.total_h)
        return not full.collidepoint(pos)


# ── Initiative panel ──────────────────────────────────────────────────────────

class InitiativePanel:
    """Right-side overlay showing turn order with HP bars."""

    ROW_H = 52
    PAD   = 6

    def __init__(self, font, small_font):
        self.font           = font
        self.small_font     = small_font
        self.visible        = False
        self.editing_entity = None   # direct reference to entity being edited
        self.edit_buf       = ''

    def draw(self, surface, entities, current_idx, screen_w, screen_h):
        if not self.visible:
            return

        panel_x = screen_w - INIT_PANEL_WIDTH
        panel_h = screen_h - TOOLBAR_HEIGHT

        # Semi-transparent background
        overlay = pygame.Surface((INIT_PANEL_WIDTH, panel_h), pygame.SRCALPHA)
        overlay.fill((20, 20, 30, 210))
        surface.blit(overlay, (panel_x, TOOLBAR_HEIGHT))
        pygame.draw.rect(surface, PANEL_BORDER,
                         (panel_x, TOOLBAR_HEIGHT, INIT_PANEL_WIDTH, panel_h), 1)

        # Header
        hdr = self.font.render('Initiative Order', True, YELLOW)
        surface.blit(hdr, (panel_x + self.PAD, TOOLBAR_HEIGHT + self.PAD))

        # Group action buttons beneath the header
        gbw = (INIT_PANEL_WIDTH - self.PAD * 2 - 4) // 2
        gby = TOOLBAR_HEIGHT + 28
        self._grp_dmg_rect  = pygame.Rect(panel_x + self.PAD,              gby, gbw, 24)
        self._grp_heal_rect = pygame.Rect(panel_x + self.PAD + gbw + 4,    gby, gbw, 24)
        pygame.draw.rect(surface, (110, 25, 25), self._grp_dmg_rect,  border_radius=4)
        pygame.draw.rect(surface, (25, 95, 40),  self._grp_heal_rect, border_radius=4)
        for rect, lbl in [(self._grp_dmg_rect, 'Group DMG'),
                          (self._grp_heal_rect, 'Group Heal')]:
            t = self.small_font.render(lbl, True, WHITE)
            surface.blit(t, (rect.centerx - t.get_width() // 2,
                             rect.centery - t.get_height() // 2))

        y = TOOLBAR_HEIGHT + 56
        for idx, ent in enumerate(entities):
            row_rect = pygame.Rect(panel_x + 2, y, INIT_PANEL_WIDTH - 4, self.ROW_H)
            # Highlight current turn
            if idx == current_idx:
                pygame.draw.rect(surface, (0, 80, 140), row_rect)
            elif idx % 2 == 0:
                pygame.draw.rect(surface, (35, 35, 45), row_rect)

            # Top half (y to y+34): icon + name + initiative
            TOP_H  = 34
            ico_sz = 22
            ico_y  = y + (TOP_H - ico_sz) // 2   # = y + 6
            sw_rect = pygame.Rect(panel_x + self.PAD, ico_y, ico_sz, ico_sz)
            if ent.image:
                img = pygame.transform.scale(ent.image, (ico_sz, ico_sz))
                surface.blit(img, sw_rect)
            else:
                pygame.draw.rect(surface, ent.color, sw_rect)

            name_surf = self.font.render(ent.name[:14], True, WHITE)
            name_y = y + (TOP_H - name_surf.get_height()) // 2
            surface.blit(name_surf, (panel_x + self.PAD + ico_sz + 4, name_y))
            if ent.is_enemy and getattr(ent, 'scene_id', 1) == 0:
                pygame.draw.circle(surface, BLUE,
                                   (panel_x + self.PAD + ico_sz + 4 + name_surf.get_width() + 8,
                                    y + TOP_H // 2), 5)

            init_str = self.edit_buf + '|' \
                       if (self.editing_entity is ent) else str(ent.initiative)
            init_surf = self.font.render(init_str, True, YELLOW)
            surface.blit(init_surf, (panel_x + INIT_PANEL_WIDTH - 34,
                                     y + (TOP_H - init_surf.get_height()) // 2))

            # Bottom half (y+34 to y+ROW_H): HP text + bar
            BOT_H     = self.ROW_H - TOP_H
            hp_str    = f"{ent.hp}/{ent.max_hp}"
            hp_surf   = self.small_font.render(hp_str, True, LIGHT_GRAY)
            hp_tw     = hp_surf.get_width()
            bh        = 8
            bot_cy    = y + TOP_H + BOT_H // 2
            hp_text_y = bot_cy - hp_surf.get_height() // 2
            surface.blit(hp_surf, (panel_x + self.PAD, hp_text_y))
            bx = panel_x + self.PAD + hp_tw + 5
            bw = INIT_PANEL_WIDTH - self.PAD - hp_tw - 5 - 4
            pygame.draw.rect(surface, (100, 0, 0), (bx, bot_cy - bh // 2, bw, bh))
            if ent.max_hp > 0:
                ratio = max(0.0, min(1.0, ent.hp / ent.max_hp))
                fw    = int(bw * ratio)
                col   = GREEN if ratio > 0.5 else (ORANGE if ratio > 0.25 else RED)
                if fw > 0:
                    pygame.draw.rect(surface, col, (bx, bot_cy - bh // 2, fw, bh))

            y += self.ROW_H
            if y + self.ROW_H > screen_h:
                break

    def hit_group_btn(self, pos, screen_w):
        """Return 'group_damage', 'group_heal', or None."""
        if not self.visible or pos[0] < screen_w - INIT_PANEL_WIDTH:
            return None
        if hasattr(self, '_grp_dmg_rect') and self._grp_dmg_rect.collidepoint(pos):
            return 'group_damage'
        if hasattr(self, '_grp_heal_rect') and self._grp_heal_rect.collidepoint(pos):
            return 'group_heal'
        return None

    def hit_row(self, pos, entities, screen_w, screen_h):
        """Return entity index if pos hits a row in the panel."""
        if not self.visible:
            return None
        panel_x = screen_w - INIT_PANEL_WIDTH
        if pos[0] < panel_x:
            return None
        y = TOOLBAR_HEIGHT + 56
        for idx, ent in enumerate(entities):
            row_rect = pygame.Rect(panel_x + 2, y, INIT_PANEL_WIDTH - 4, self.ROW_H)
            if row_rect.collidepoint(pos):
                return idx
            y += self.ROW_H
            if y > screen_h:
                break
        return None

    def is_over(self, pos, screen_w):
        return self.visible and pos[0] >= screen_w - INIT_PANEL_WIDTH

    def start_edit(self, entity):
        self.editing_entity = entity
        self.edit_buf       = str(entity.initiative)

    def stop_edit(self):
        self.editing_entity = None
        self.edit_buf       = ''

    def key(self, event):
        """Feed a KEYDOWN event while editing. Returns new value or None."""
        if self.editing_entity is None:
            return None
        if event.key == pygame.K_RETURN:
            try:
                val = int(self.edit_buf)
            except ValueError:
                val = 0
            self.stop_edit()
            return val
        if event.key == pygame.K_ESCAPE:
            self.stop_edit()
            return None
        if event.key == pygame.K_BACKSPACE:
            self.edit_buf = self.edit_buf[:-1]
        elif event.unicode.lstrip('-').isdigit() or \
             (event.unicode == '-' and not self.edit_buf):
            self.edit_buf += event.unicode
        return None


# ── HP popup ──────────────────────────────────────────────────────────────────

class HPPopup:
    """Modal popup for adjusting an entity's HP."""

    W = 460; H = 260

    def __init__(self, entity, font, screen_w, screen_h):
        self.entity = entity
        self.font   = font
        self.x      = (screen_w - self.W) // 2
        self.y      = (screen_h - self.H) // 2
        self._build()

    def _build(self):
        bw = 64; bh = 44; gap = 8
        row_y = self.y + 100
        labels = [('-10', -10), ('-5', -5), ('-1', -1),
                  ('+1',   1),  ('+5',  5),  ('+10', 10)]
        start_x = self.x + (self.W - (bw * 6 + gap * 5)) // 2
        self.btns = []
        for lbl, delta in labels:
            rect = pygame.Rect(start_x, row_y, bw, bh)
            self.btns.append((rect, lbl, delta))
            start_x += bw + gap

        # Max HP row — two small +1/-1 buttons centred under the HP row
        mhp_y = row_y + bh + gap
        self.max_btns = []
        mbw = 56; mgap = 8
        mb_start = self.x + (self.W - mbw * 2 - mgap) // 2
        for lbl, delta in [('-1', -1), ('+1', 1)]:
            rect = pygame.Rect(mb_start, mhp_y, mbw, 36)
            self.max_btns.append((rect, lbl, delta))
            mb_start += mbw + mgap

        # Action row — Full Heal and Set as Max
        act_y  = mhp_y + 36 + 10
        abw    = (self.W - 48) // 2
        self.full_heal_rect  = pygame.Rect(self.x + 16,          act_y, abw, 38)
        self.set_max_rect    = pygame.Rect(self.x + 16 + abw + 8, act_y, abw, 38)

        close_x = self.x + self.W - 44
        close_y = self.y + 4
        self.close_rect = pygame.Rect(close_x, close_y, 40, 32)

    def draw(self, surface):
        pygame.draw.rect(surface, PANEL_BG,     (self.x, self.y, self.W, self.H), border_radius=8)
        pygame.draw.rect(surface, PANEL_BORDER, (self.x, self.y, self.W, self.H), 2, border_radius=8)

        # Title & HP display
        title = self.font.render(f"HP - {self.entity.name}", True, WHITE)
        surface.blit(title, (self.x + 10, self.y + 8))
        hp_str = f"{self.entity.hp} / {self.entity.max_hp}"
        hp_surf = pygame.font.Font(None, 48).render(hp_str, True, YELLOW)
        surface.blit(hp_surf, (self.x + self.W // 2 - hp_surf.get_width() // 2,
                               self.y + 44))

        # HP adjustment buttons
        for rect, lbl, _ in self.btns:
            bg = (80, 40, 40) if lbl.startswith('-') else (40, 80, 40)
            pygame.draw.rect(surface, bg, rect, border_radius=6)
            t = self.font.render(lbl, True, WHITE)
            surface.blit(t, (rect.centerx - t.get_width() // 2,
                             rect.centery - t.get_height() // 2))

        # Max HP controls
        lbl_s = self.font.render(f"Max: {self.entity.max_hp}", True, LIGHT_GRAY)
        surface.blit(lbl_s, (self.x + self.W // 2 - lbl_s.get_width() // 2,
                             self.y + 160))
        for rect, lbl, _ in self.max_btns:
            pygame.draw.rect(surface, TOOLBAR_BTN, rect, border_radius=5)
            t = self.font.render(lbl, True, WHITE)
            surface.blit(t, (rect.centerx - t.get_width() // 2,
                             rect.centery - t.get_height() // 2))

        # Full Heal button
        pygame.draw.rect(surface, (25, 110, 50), self.full_heal_rect, border_radius=6)
        fh_t = self.font.render('Full Heal', True, WHITE)
        surface.blit(fh_t, (self.full_heal_rect.centerx - fh_t.get_width() // 2,
                            self.full_heal_rect.centery - fh_t.get_height() // 2))

        # Set as Max button
        pygame.draw.rect(surface, (30, 80, 140), self.set_max_rect, border_radius=6)
        sm_t = self.font.render('Set as Max', True, WHITE)
        surface.blit(sm_t, (self.set_max_rect.centerx - sm_t.get_width() // 2,
                            self.set_max_rect.centery - sm_t.get_height() // 2))

        # Close button
        pygame.draw.rect(surface, (120, 30, 30), self.close_rect, border_radius=5)
        t = self.font.render('X', True, WHITE)
        surface.blit(t, (self.close_rect.centerx - t.get_width() // 2,
                         self.close_rect.centery - t.get_height() // 2))

    def hit(self, pos):
        """
        Returns ('close', None), ('hp', delta), ('max_hp', delta),
        ('full_heal', None), ('set_as_max', None), or (None, None).
        """
        if self.close_rect.collidepoint(pos):
            return ('close', None)
        for rect, _, delta in self.btns:
            if rect.collidepoint(pos):
                return ('hp', delta)
        for rect, _, delta in self.max_btns:
            if rect.collidepoint(pos):
                return ('max_hp', delta)
        if self.full_heal_rect.collidepoint(pos):
            return ('full_heal', None)
        if self.set_max_rect.collidepoint(pos):
            return ('set_as_max', None)
        return (None, None)


# ── Group Damage / Healing popup ──────────────────────────────────────────────

class GroupHPPopup:
    """Multi-select popup for applying a flat damage or heal to several entities."""

    W           = 520
    PAD         = 10
    ROW_H       = 38
    MAX_VISIBLE = 8

    def __init__(self, entities, font, small_font, screen_w, screen_h):
        self.entities  = list(entities)
        self.font      = font
        self.sf        = small_font
        self.selected  = {e.id for e in entities}   # all pre-selected
        self.amt_buf   = ''
        self.scroll    = 0
        self._sw       = screen_w
        self._sh       = screen_h
        self._rebuild()

    def _rebuild(self):
        n_vis  = min(len(self.entities), self.MAX_VISIBLE)
        list_h = n_vis * self.ROW_H
        H = 44 + 30 + list_h + 14 + 18 + 48 + 12 + 48 + self.PAD
        self.H    = H
        self.n_vis = n_vis
        self.x    = (self._sw - self.W) // 2
        self.y    = (self._sh - H)  // 2

        lx = self.x + self.PAD

        self.close_rect = pygame.Rect(self.x + self.W - 44, self.y + 8, 36, 28)
        self.all_rect   = pygame.Rect(self.x + self.W - 140, self.y + 46, 60, 22)
        self.none_rect  = pygame.Rect(self.x + self.W - 74,  self.y + 46, 60, 22)

        self.list_rect  = pygame.Rect(lx, self.y + 72, self.W - self.PAD * 2, list_h)
        self._row_rects = [
            pygame.Rect(lx, self.list_rect.y + i * self.ROW_H,
                        self.W - self.PAD * 2, self.ROW_H)
            for i in range(n_vis)
        ]

        ay = self.list_rect.bottom + 14
        self._amt_lbl_y = ay
        self.amt_rect   = pygame.Rect(lx, ay + 18, self.W - self.PAD * 2, 44)

        bw = (self.W - self.PAD * 2 - 16) // 3
        by = self.amt_rect.bottom + 10
        self.dmg_rect    = pygame.Rect(lx,              by, bw, 44)
        self.heal_rect   = pygame.Rect(lx + bw + 8,     by, bw, 44)
        self.cancel_rect = pygame.Rect(lx + (bw + 8)*2, by, bw, 44)

        # Full Heal row — spans full width below the damage/heal row
        fby = by + 44 + 8
        self.full_heal_rect = pygame.Rect(lx, fby, self.W - self.PAD * 2, 38)
        self.H += 46   # extend popup height for the new row

    def scroll_list(self, delta):
        self.scroll = max(0, min(max(0, len(self.entities) - self.n_vis),
                                 self.scroll + delta))

    def _amount(self):
        try:   return max(0, int(self.amt_buf))
        except ValueError: return 0

    def draw(self, surface):
        pygame.draw.rect(surface, PANEL_BG,     (self.x, self.y, self.W, self.H), border_radius=8)
        pygame.draw.rect(surface, PANEL_BORDER, (self.x, self.y, self.W, self.H), 2, border_radius=8)

        # Title
        t = self.font.render('Group Damage / Healing', True, WHITE)
        surface.blit(t, (self.x + self.PAD, self.y + 12))

        # Close button
        pygame.draw.rect(surface, (120, 30, 30), self.close_rect, border_radius=5)
        t = self.font.render('X', True, WHITE)
        surface.blit(t, (self.close_rect.centerx - t.get_width() // 2,
                         self.close_rect.centery - t.get_height() // 2))

        # "Select targets" + All / None
        lbl = self.sf.render('Select targets:', True, LIGHT_GRAY)
        surface.blit(lbl, (self.x + self.PAD, self.y + 49))
        for rect, txt in [(self.all_rect, 'All'), (self.none_rect, 'None')]:
            pygame.draw.rect(surface, TOOLBAR_BTN, rect, border_radius=4)
            t = self.sf.render(txt, True, WHITE)
            surface.blit(t, (rect.centerx - t.get_width() // 2,
                             rect.centery - t.get_height() // 2))

        # List background
        pygame.draw.rect(surface, (22, 22, 38), self.list_rect, border_radius=4)
        pygame.draw.rect(surface, (55, 55, 75), self.list_rect, 1, border_radius=4)

        # Entity rows
        for i, ent in enumerate(self.entities[self.scroll: self.scroll + self.n_vis]):
            rr      = self._row_rects[i]
            checked = ent.id in self.selected
            if i % 2 == 0:
                pygame.draw.rect(surface, (28, 28, 46), rr)

            # Checkbox
            cb = pygame.Rect(rr.x + 5, rr.centery - 9, 18, 18)
            pygame.draw.rect(surface, (GREEN if checked else TOOLBAR_BTN), cb, border_radius=3)
            if checked:
                # Draw a tick mark using lines (avoids font glyph issues)
                cx, cy = cb.x, cb.y
                pygame.draw.line(surface, BLACK, (cx + 3, cy + 9),  (cx + 7, cy + 13), 3)
                pygame.draw.line(surface, BLACK, (cx + 7, cy + 13), (cx + 14, cy + 4), 3)
            else:
                pygame.draw.rect(surface, (80, 80, 100), cb, 1, border_radius=3)

            # Type tag
            if ent.is_enemy:
                tag, tcol = 'Enemy', (150, 40, 40)
            elif getattr(ent, 'is_npc', False):
                tag, tcol = 'NPC', (70, 70, 160)
            else:
                tag, tcol = 'Player', (40, 110, 60)
            ts   = self.sf.render(tag, True, WHITE)
            trct = pygame.Rect(rr.x + 28, rr.centery - 10, ts.get_width() + 8, 20)
            pygame.draw.rect(surface, tcol, trct, border_radius=3)
            surface.blit(ts, (trct.x + 4, trct.y + 2))

            # Name + HP
            ns = self.font.render(ent.name[:20], True, WHITE if checked else LIGHT_GRAY)
            surface.blit(ns, (trct.right + 8, rr.centery - ns.get_height() // 2))
            hs = self.sf.render(f'{ent.hp}/{ent.max_hp}', True, LIGHT_GRAY)
            surface.blit(hs, (rr.right - hs.get_width() - 6,
                              rr.centery - hs.get_height() // 2))

        # Scroll hint
        if len(self.entities) > self.n_vis:
            si = self.sf.render(
                f'↑↓ scroll  ({self.scroll+1}–'
                f'{min(self.scroll+self.n_vis, len(self.entities))} of {len(self.entities)})',
                True, (90, 90, 120))
            surface.blit(si, (self.list_rect.centerx - si.get_width() // 2,
                               self.list_rect.bottom + 3))

        # Amount field
        al = self.sf.render('Amount:', True, LIGHT_GRAY)
        surface.blit(al, (self.x + self.PAD, self._amt_lbl_y))
        pygame.draw.rect(surface, (25, 28, 45), self.amt_rect, border_radius=5)
        pygame.draw.rect(surface, YELLOW,       self.amt_rect, 2, border_radius=5)
        blink = (pygame.time.get_ticks() // 500) % 2 == 0
        disp  = (self.amt_buf + ('|' if blink else '')) or ('|' if blink else '0')
        at = pygame.font.Font(None, 40).render(disp, True, WHITE)
        surface.blit(at, (self.amt_rect.centerx - at.get_width() // 2,
                          self.amt_rect.centery - at.get_height() // 2))

        # Damage / Heal / Cancel
        pygame.draw.rect(surface, (100, 20, 20), self.dmg_rect, border_radius=6)
        dt = self.font.render('Damage', True, (252, 165, 165))
        surface.blit(dt, (self.dmg_rect.centerx - dt.get_width() // 2,
                          self.dmg_rect.centery - dt.get_height() // 2))

        pygame.draw.rect(surface, (20, 85, 35), self.heal_rect, border_radius=6)
        ht = self.font.render('Heal', True, (134, 239, 172))
        surface.blit(ht, (self.heal_rect.centerx - ht.get_width() // 2,
                          self.heal_rect.centery - ht.get_height() // 2))

        pygame.draw.rect(surface, TOOLBAR_BTN, self.cancel_rect, border_radius=6)
        ct = self.font.render('Cancel', True, LIGHT_GRAY)
        surface.blit(ct, (self.cancel_rect.centerx - ct.get_width() // 2,
                          self.cancel_rect.centery - ct.get_height() // 2))

        # Full Heal Selected button
        pygame.draw.rect(surface, (25, 110, 50), self.full_heal_rect, border_radius=6)
        fht = self.font.render('Full Heal Selected', True, WHITE)
        surface.blit(fht, (self.full_heal_rect.centerx - fht.get_width() // 2,
                           self.full_heal_rect.centery - fht.get_height() // 2))

    def hit(self, pos):
        """Returns ('close',0,None), ('damage',amt,ids), ('heal',amt,ids),
           ('full_heal',0,ids), or (None,None,None) for internal state changes."""
        if not pygame.Rect(self.x, self.y, self.W, self.H).collidepoint(pos):
            return (None, None, None)
        if self.close_rect.collidepoint(pos) or self.cancel_rect.collidepoint(pos):
            return ('close', 0, None)
        if self.all_rect.collidepoint(pos):
            self.selected = {e.id for e in self.entities}
            return (None, None, None)
        if self.none_rect.collidepoint(pos):
            self.selected.clear()
            return (None, None, None)
        if self.list_rect.collidepoint(pos):
            for i, rr in enumerate(self._row_rects):
                if rr.collidepoint(pos):
                    idx = self.scroll + i
                    if idx < len(self.entities):
                        eid = self.entities[idx].id
                        if eid in self.selected: self.selected.discard(eid)
                        else:                    self.selected.add(eid)
                    return (None, None, None)
        amt = self._amount()
        ids = {e.id for e in self.entities if e.id in self.selected}
        if self.dmg_rect.collidepoint(pos):
            return ('damage', amt, ids)
        if self.heal_rect.collidepoint(pos):
            return ('heal', amt, ids)
        if self.full_heal_rect.collidepoint(pos):
            return ('full_heal', 0, ids)
        return (None, None, None)

    def key(self, event):
        """Handle KEYDOWN. Returns same tuple as hit() or (None,None,None)."""
        if event.key == pygame.K_ESCAPE:
            return ('close', 0, None)
        if event.key == pygame.K_BACKSPACE:
            self.amt_buf = self.amt_buf[:-1]
        elif event.unicode.isdigit() and len(self.amt_buf) < 6:
            self.amt_buf += event.unicode
        return (None, None, None)


# ── Conditions popup ──────────────────────────────────────────────────────────

class ConditionsPopup:
    """Grid of toggleable condition chips for an entity."""

    CHIP_W = 120; CHIP_H = 40; COLS = 2; PAD = 6

    def __init__(self, entity, font, screen_w, screen_h):
        self.entity = entity
        self.font   = font
        rows   = (len(CONDITION_CODES) + self.COLS - 1) // self.COLS
        self.W = self.COLS * self.CHIP_W + (self.COLS + 1) * self.PAD
        self.H = rows   * self.CHIP_H + (rows   + 1) * self.PAD + 36
        self.x = (screen_w - self.W) // 2
        self.y = (screen_h - self.H) // 2
        self._build()

    def _build(self):
        self.btns = []
        for i, code in enumerate(CONDITION_CODES):
            col = i % self.COLS
            row = i // self.COLS
            rx  = self.x + self.PAD + col * (self.CHIP_W + self.PAD)
            ry  = self.y + 36 + self.PAD + row * (self.CHIP_H + self.PAD)
            self.btns.append((code, pygame.Rect(rx, ry, self.CHIP_W, self.CHIP_H)))
        self.close_rect = pygame.Rect(self.x + self.W - 40, self.y + 4, 36, 28)

    def draw(self, surface):
        pygame.draw.rect(surface, PANEL_BG, (self.x, self.y, self.W, self.H),
                         border_radius=8)
        pygame.draw.rect(surface, PANEL_BORDER, (self.x, self.y, self.W, self.H),
                         2, border_radius=8)
        title = self.font.render(f"Conditions - {self.entity.name}", True, WHITE)
        surface.blit(title, (self.x + self.PAD, self.y + 8))

        for code, rect in self.btns:
            _, chip_col, full_name = CONDITIONS[code]
            active = code in self.entity.conditions
            bg = chip_col if active else TOOLBAR_BTN
            pygame.draw.rect(surface, bg, rect, border_radius=5)
            if active:
                pygame.draw.rect(surface, WHITE, rect, 2, border_radius=5)
            t = self.font.render(full_name, True, BLACK if active else LIGHT_GRAY)
            surface.blit(t, (rect.x + 4, rect.centery - t.get_height() // 2))

        pygame.draw.rect(surface, (120, 30, 30), self.close_rect, border_radius=4)
        t = self.font.render('X', True, WHITE)
        surface.blit(t, (self.close_rect.centerx - t.get_width() // 2,
                         self.close_rect.centery - t.get_height() // 2))

    def hit(self, pos):
        """Returns ('close', None) or ('toggle', code) or (None, None)."""
        if self.close_rect.collidepoint(pos):
            return ('close', None)
        for code, rect in self.btns:
            if rect.collidepoint(pos):
                return ('toggle', code)
        return (None, None)


# ── Character dialog ──────────────────────────────────────────────────────────

class CharacterDialog:
    """
    Modal dialog for creating a new player character or editing an existing one.

    Returns from handle_event():
      'cancel'  — dismissed without saving
      dict      — {'name', 'color', 'size', 'max_hp'}  on confirm
      None      — event consumed, still open
    """

    W = 440; H = 610

    # Preset colour palette  (hex, display name)
    COLORS = [
        ('#e74c3c', 'Red'),    ('#e67e22', 'Orange'), ('#f1c40f', 'Yellow'), ('#2ecc71', 'Green'),
        ('#1abc9c', 'Teal'),   ('#3498db', 'Blue'),   ('#9b59b6', 'Purple'), ('#e91e8c', 'Pink'),
        ('#ffffff', 'White'),  ('#95a5a6', 'Silver'), ('#7f8c8d', 'Grey'),   ('#2c3e50', 'Dark'),
    ]
    SIZES = SIZE_PRESETS   # (radius px, label) — from constants

    def __init__(self, font, small_font, screen_w, screen_h, entity=None):
        self.font       = font
        self.small_font = small_font
        self.mode       = 'edit' if entity else 'create'
        self.entity     = entity
        self.x          = (screen_w - self.W) // 2
        self.y          = (screen_h - self.H) // 2
        self._zenity_proc  = None   # non-blocking zenity process (Linux)
        self._tk_thread    = None   # non-blocking tkinter thread (Windows/Mac)
        self._tk_result    = None   # list populated by the thread when done
        self._preview_surf = None   # cached scaled preview of the chosen image
        self._preview_path = ''     # path that _preview_surf was loaded from

        # Pre-fill values
        if entity:
            self.name_buf       = entity.name
            self.sel_color_idx  = self._nearest_color(entity.color)
            self.sel_size_idx   = self._nearest_size(entity.size)
            self.max_hp         = entity.max_hp
            self.init_bonus     = getattr(entity, 'init_bonus', 0)
            self.image_path     = getattr(entity, 'image_path', '') or ''
            self.is_npc         = getattr(entity, 'is_npc', False)
        else:
            self.name_buf       = ''
            self.sel_color_idx  = 5   # Blue default
            self.sel_size_idx   = 2   # Medium default
            self.max_hp         = 10
            self.init_bonus     = 0
            self.image_path     = ''
            self.is_npc         = False

        self._build()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build(self):
        bx, by = self.x, self.y
        pad = 12

        self.close_rect = pygame.Rect(bx + self.W - 36, by + 6, 30, 28)
        self.name_rect  = pygame.Rect(bx + pad + 54, by + 46, self.W - 66 - pad, 34)

        # Colour swatches: 4 columns
        sw = 34; gap = 6
        self.color_rects = []
        for i in range(len(self.COLORS)):
            col = i % 4; row = i // 4
            self.color_rects.append(pygame.Rect(
                bx + pad + col * (sw + gap),
                by + 106 + row * (sw + gap),
                sw, sw
            ))

        # Size buttons: 2 rows of 3 so all 6 fit comfortably
        sb_cols = 3; sb_h = 36; sb_gap = 6
        sb_w = (self.W - 2 * pad - (sb_cols - 1) * sb_gap) // sb_cols
        self.size_rects = [
            pygame.Rect(
                bx + pad + (i % sb_cols) * (sb_w + sb_gap),
                by + 244 + (i // sb_cols) * (sb_h + sb_gap),
                sb_w, sb_h
            )
            for i in range(len(self.SIZES))
        ]

        # Max-HP ± buttons
        self.hp_minus = pygame.Rect(bx + self.W // 2 - 70, by + 346, 44, 36)
        self.hp_plus  = pygame.Rect(bx + self.W // 2 + 26, by + 346, 44, 36)

        # Initiative Bonus ± buttons
        self.ib_minus = pygame.Rect(bx + self.W // 2 - 70, by + 400, 44, 36)
        self.ib_plus  = pygame.Rect(bx + self.W // 2 + 26, by + 400, 44, 36)

        # Icon / image picker  (shifted down 54px)
        self.browse_rect = pygame.Rect(bx + self.W - pad - 90, by + 456, 90, 32)

        # NPC checkbox  (shifted down 54px)
        self.npc_check_rect = pygame.Rect(bx + pad, by + 506, 22, 22)

        # Confirm / Cancel
        self.cancel_rect  = pygame.Rect(bx + pad,                by + self.H - 50, 120, 42)
        self.confirm_rect = pygame.Rect(bx + self.W - 160 - pad, by + self.H - 50, 160, 42)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _browse_image(self):
        pygame.event.set_grab(False)
        pygame.mouse.set_visible(True)
        pygame.event.pump()
        try:
            import ctypes as _ct
            _ct.CDLL('libSDL2-2.0.so.0').SDL_CaptureMouse(_ct.c_int(0))
        except Exception:
            pass
        try:
            self._zenity_proc = _subprocess.Popen(
                ['zenity', '--file-selection',
                 '--title=Select character icon',
                 '--file-filter=Images (png jpg jpeg bmp gif) | *.png *.jpg *.jpeg *.bmp *.gif',
                 '--file-filter=All files | *'],
                stdout=_subprocess.PIPE, stderr=_subprocess.DEVNULL
            )
        except FileNotFoundError:
            # zenity not available (Windows/Mac) — use tkinter in a thread so the
            # SDL event loop keeps running while the native dialog is open.
            self._zenity_proc = None
            self._tk_result   = []
            import threading as _threading
            def _run(out):
                try:
                    import tkinter as _tk
                    from tkinter import filedialog as _fd
                    root = _tk.Tk()
                    root.withdraw()
                    root.attributes('-topmost', True)
                    path = _fd.askopenfilename(
                        title='Select character icon',
                        filetypes=[
                            ('Images', '*.png *.jpg *.jpeg *.bmp *.gif'),
                            ('All files', '*.*'),
                        ],
                    )
                    root.destroy()
                    out.append(path or '')
                except Exception:
                    out.append('')
            self._tk_thread = _threading.Thread(target=_run, args=(self._tk_result,), daemon=True)
            self._tk_thread.start()

    def _nearest_color(self, pg_color):
        r, g, b = pg_color.r, pg_color.g, pg_color.b
        best, best_d = 0, float('inf')
        for i, (h, _) in enumerate(self.COLORS):
            c = pygame.Color(h)
            d = (c.r-r)**2 + (c.g-g)**2 + (c.b-b)**2
            if d < best_d:
                best, best_d = i, d
        return best

    def _nearest_size(self, size):
        best, best_d = 0, float('inf')
        for i, (s, _) in enumerate(self.SIZES):
            if abs(s - size) < best_d:
                best, best_d = i, abs(s - size)
        return best

    # ── Drawing ───────────────────────────────────────────────────────────────

    def draw(self, surface):
        # Poll non-blocking zenity file picker (Linux)
        if self._zenity_proc is not None and self._zenity_proc.poll() is not None:
            path = self._zenity_proc.stdout.read().decode().strip()
            self._zenity_proc = None
            if path:
                self.image_path = path

        # Poll tkinter file dialog thread (Windows/Mac)
        if self._tk_thread is not None and not self._tk_thread.is_alive():
            self._tk_thread = None
            if self._tk_result:
                path = self._tk_result.pop()
                self._tk_result = None
                if path:
                    self.image_path = path

        # Refresh preview surface whenever the path changes
        if self.image_path != self._preview_path:
            self._preview_path = self.image_path
            self._preview_surf = None
            if self.image_path:
                try:
                    import campaigns as _cm
                    resolved = _cm.resolve_image_path(self.image_path)
                    self._preview_surf = pygame.image.load(resolved).convert_alpha()
                except Exception:
                    self._preview_surf = None

        pygame.draw.rect(surface, PANEL_BG,
                         (self.x, self.y, self.W, self.H), border_radius=8)
        pygame.draw.rect(surface, PANEL_BORDER,
                         (self.x, self.y, self.W, self.H), 2, border_radius=8)

        title = 'Edit Character' if self.mode == 'edit' else 'New Character'
        surface.blit(self.font.render(title, True, WHITE), (self.x + 12, self.y + 8))

        # Close ✕
        pygame.draw.rect(surface, (120, 30, 30), self.close_rect, border_radius=4)
        t = self.font.render('X', True, WHITE)
        surface.blit(t, (self.close_rect.centerx - t.get_width()//2,
                         self.close_rect.centery - t.get_height()//2))

        # Name field
        surface.blit(self.font.render('Name:', True, LIGHT_GRAY), (self.x + 12, self.y + 54))
        pygame.draw.rect(surface, TOOLBAR_BTN,   self.name_rect, border_radius=4)
        pygame.draw.rect(surface, PANEL_BORDER,  self.name_rect, 1, border_radius=4)
        surface.blit(self.font.render(self.name_buf + '|', True, WHITE),
                     (self.name_rect.x + 6, self.name_rect.y + 6))

        # Colour label + swatches
        surface.blit(self.font.render('Colour:', True, LIGHT_GRAY), (self.x + 12, self.y + 90))
        for i, (rect, (hex_c, _)) in enumerate(zip(self.color_rects, self.COLORS)):
            pygame.draw.rect(surface, pygame.Color(hex_c), rect, border_radius=4)
            if i == self.sel_color_idx:
                pygame.draw.rect(surface, WHITE, rect, 3, border_radius=4)

        # Token preview (right side of colour grid)
        preview_x = self.x + self.W - 56
        preview_y = self.y + 140
        sel_color = pygame.Color(self.COLORS[self.sel_color_idx][0])
        sel_size  = self.SIZES[self.sel_size_idx][0]
        if self._preview_surf is not None:
            scaled = pygame.transform.scale(self._preview_surf, (sel_size * 2, sel_size * 2))
            surface.blit(scaled, (preview_x - sel_size, preview_y - sel_size))
        else:
            pygame.draw.circle(surface, sel_color, (preview_x, preview_y), sel_size)
        surface.blit(self.small_font.render('Preview', True, GRAY),
                     (preview_x - 22, preview_y + sel_size + 4))

        # Size label + buttons (2 rows of 3)
        surface.blit(self.font.render('Size:', True, LIGHT_GRAY), (self.x + 12, self.y + 228))
        for i, (rect, (_, lbl)) in enumerate(zip(self.size_rects, self.SIZES)):
            bg = TOOLBAR_BTN_ACTIVE if i == self.sel_size_idx else TOOLBAR_BTN
            pygame.draw.rect(surface, bg, rect, border_radius=5)
            t = self.font.render(lbl, True, WHITE)
            surface.blit(t, (rect.centerx - t.get_width()//2,
                             rect.centery - t.get_height()//2))

        # Max HP
        surface.blit(self.font.render('Max HP:', True, LIGHT_GRAY), (self.x + 12, self.y + 354))
        pygame.draw.rect(surface, (80, 40, 40), self.hp_minus, border_radius=5)
        surface.blit(self.font.render('-', True, WHITE),
                     (self.hp_minus.centerx - 4, self.hp_minus.centery - 10))
        hp_t = self.font.render(str(self.max_hp), True, YELLOW)
        surface.blit(hp_t, (self.x + self.W//2 - hp_t.get_width()//2, self.y + 354))
        pygame.draw.rect(surface, (40, 80, 40), self.hp_plus, border_radius=5)
        surface.blit(self.font.render('+', True, WHITE),
                     (self.hp_plus.centerx - 4, self.hp_plus.centery - 10))

        # Initiative Bonus
        surface.blit(self.font.render('Init Bonus:', True, LIGHT_GRAY), (self.x + 12, self.y + 408))
        pygame.draw.rect(surface, (80, 40, 40), self.ib_minus, border_radius=5)
        surface.blit(self.font.render('-', True, WHITE),
                     (self.ib_minus.centerx - 4, self.ib_minus.centery - 10))
        ib_str = ('+' if self.init_bonus > 0 else '') + str(self.init_bonus)
        ib_t = self.font.render(ib_str, True, YELLOW)
        surface.blit(ib_t, (self.x + self.W//2 - ib_t.get_width()//2, self.y + 408))
        pygame.draw.rect(surface, (40, 80, 40), self.ib_plus, border_radius=5)
        surface.blit(self.font.render('+', True, WHITE),
                     (self.ib_plus.centerx - 4, self.ib_plus.centery - 10))

        # Icon picker
        surface.blit(self.font.render('Icon:', True, LIGHT_GRAY), (self.x + 12, self.y + 462))
        pygame.draw.rect(surface, TOOLBAR_BTN, self.browse_rect, border_radius=5)
        bt = self.font.render('Browse...', True, WHITE)
        surface.blit(bt, (self.browse_rect.centerx - bt.get_width()//2,
                          self.browse_rect.centery - bt.get_height()//2))
        # Show truncated filename between label and button
        fname = self.image_path.replace('\\', '/').split('/')[-1] if self.image_path else 'None'
        fn_surf = self.small_font.render(fname[:28], True, LIGHT_GRAY)
        surface.blit(fn_surf, (self.x + 60, self.y + 466))

        # NPC checkbox
        pygame.draw.rect(surface, TOOLBAR_BTN, self.npc_check_rect, border_radius=3)
        pygame.draw.rect(surface, PANEL_BORDER, self.npc_check_rect, 1, border_radius=3)
        if self.is_npc:
            pygame.draw.line(surface, WHITE,
                             (self.npc_check_rect.x + 3, self.npc_check_rect.centery),
                             (self.npc_check_rect.centerx - 1, self.npc_check_rect.bottom - 4), 2)
            pygame.draw.line(surface, WHITE,
                             (self.npc_check_rect.centerx - 1, self.npc_check_rect.bottom - 4),
                             (self.npc_check_rect.right - 3, self.npc_check_rect.top + 4), 2)
        npc_lbl = self.font.render('NPC  (excluded from group movement)', True, LIGHT_GRAY)
        surface.blit(npc_lbl, (self.npc_check_rect.right + 8,
                                self.npc_check_rect.centery - npc_lbl.get_height() // 2))

        # Cancel / Confirm
        pygame.draw.rect(surface, TOOLBAR_BTN, self.cancel_rect, border_radius=6)
        t = self.font.render('Cancel', True, WHITE)
        surface.blit(t, (self.cancel_rect.centerx - t.get_width()//2,
                         self.cancel_rect.centery - t.get_height()//2))

        conf_lbl = 'Save Changes' if self.mode == 'edit' else 'Add Character'
        pygame.draw.rect(surface, TOOLBAR_BTN_ACTIVE, self.confirm_rect, border_radius=6)
        t = self.font.render(conf_lbl, True, WHITE)
        surface.blit(t, (self.confirm_rect.centerx - t.get_width()//2,
                         self.confirm_rect.centery - t.get_height()//2))

    # ── Event handling ────────────────────────────────────────────────────────

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                return 'cancel'
            if event.key == pygame.K_RETURN:
                return self._result()
            if event.key == pygame.K_BACKSPACE:
                self.name_buf = self.name_buf[:-1]
            elif event.unicode and event.unicode.isprintable() and len(self.name_buf) < 30:
                self.name_buf += event.unicode
            return None

        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return None
        pos = event.pos

        if self.close_rect.collidepoint(pos) or self.cancel_rect.collidepoint(pos):
            return 'cancel'
        if self.confirm_rect.collidepoint(pos):
            return self._result()
        for i, rect in enumerate(self.color_rects):
            if rect.collidepoint(pos):
                self.sel_color_idx = i; return None
        for i, rect in enumerate(self.size_rects):
            if rect.collidepoint(pos):
                self.sel_size_idx = i; return None
        if self.hp_minus.collidepoint(pos):
            self.max_hp = max(1, self.max_hp - 1)
        elif self.hp_plus.collidepoint(pos):
            self.max_hp = min(999, self.max_hp + 1)
        elif self.ib_minus.collidepoint(pos):
            self.init_bonus = max(-9, self.init_bonus - 1)
        elif self.ib_plus.collidepoint(pos):
            self.init_bonus = min(20, self.init_bonus + 1)
        elif self.browse_rect.collidepoint(pos):
            self._browse_image()
        elif self.npc_check_rect.collidepoint(pos):
            self.is_npc = not self.is_npc
        return None

    def _result(self):
        fallback = self.entity.name if self.entity else 'New Character'
        return {
            'name':       self.name_buf.strip() or fallback,
            'color':      self.COLORS[self.sel_color_idx][0],
            'size':       self.SIZES[self.sel_size_idx][0],
            'max_hp':     self.max_hp,
            'init_bonus': self.init_bonus,
            'image_path': self.image_path,
            'is_npc':     self.is_npc,
        }


# ── Enemy settings dialog ─────────────────────────────────────────────────────

class EnemyDialog:
    """Edit dialog for an existing enemy token: name, colour, size, max HP, icon."""

    W = 440; H = 500

    COLORS = CharacterDialog.COLORS
    SIZES  = SIZE_PRESETS

    def __init__(self, font, small_font, screen_w, screen_h, entity):
        self.font        = font
        self.small_font  = small_font
        self.entity      = entity
        self.x           = (screen_w - self.W) // 2
        self.y           = (screen_h - self.H) // 2
        self._zenity_proc  = None
        self._tk_thread    = None
        self._tk_result    = None
        self._preview_surf = None
        self._preview_path = ''

        self.name_buf      = entity.name
        self.sel_color_idx = self._nearest_color(entity.color)
        self.sel_size_idx  = self._nearest_size(entity.size)
        self.max_hp        = entity.max_hp
        self.image_path    = getattr(entity, 'image_path', '') or ''
        self._build()

    def _nearest_color(self, color):
        best, best_d = 0, float('inf')
        r0, g0, b0 = color.r, color.g, color.b
        for i, (hex_c, _) in enumerate(self.COLORS):
            c = pygame.Color(hex_c)
            d = (c.r-r0)**2 + (c.g-g0)**2 + (c.b-b0)**2
            if d < best_d: best, best_d = i, d
        return best

    def _nearest_size(self, size):
        best, best_d = 0, float('inf')
        for i, (s, _) in enumerate(self.SIZES):
            d = abs(s - size)
            if d < best_d: best, best_d = i, d
        return best

    def _build(self):
        bx, by = self.x, self.y
        pad = 12
        self.close_rect  = pygame.Rect(bx + self.W - 36, by + 6, 30, 28)
        self.name_rect   = pygame.Rect(bx + pad + 54, by + 46, self.W - 66 - pad, 34)
        sw = 34; gap = 6
        self.color_rects = []
        for i in range(len(self.COLORS)):
            col = i % 4; row = i // 4
            self.color_rects.append(pygame.Rect(
                bx + pad + col * (sw + gap),
                by + 106 + row * (sw + gap), sw, sw))
        sb_cols = 3; sb_h = 36; sb_gap = 6
        sb_w = (self.W - 2 * pad - (sb_cols - 1) * sb_gap) // sb_cols
        self.size_rects = [
            pygame.Rect(bx + pad + (i % sb_cols) * (sb_w + sb_gap),
                        by + 244 + (i // sb_cols) * (sb_h + sb_gap), sb_w, sb_h)
            for i in range(len(self.SIZES))]
        self.hp_minus    = pygame.Rect(bx + self.W // 2 - 70, by + 346, 44, 36)
        self.hp_plus     = pygame.Rect(bx + self.W // 2 + 26, by + 346, 44, 36)
        self.browse_rect = pygame.Rect(bx + self.W - pad - 90, by + 402, 90, 32)
        self.cancel_rect  = pygame.Rect(bx + pad,                by + self.H - 50, 120, 42)
        self.confirm_rect = pygame.Rect(bx + self.W - 160 - pad, by + self.H - 50, 160, 42)

    def _browse_image(self):
        import threading, sys
        if sys.platform == 'win32':
            def _pick(result):
                try:
                    import tkinter as tk
                    from tkinter import filedialog
                    root = tk.Tk(); root.withdraw()
                    p = filedialog.askopenfilename(
                        title='Select Token Image',
                        filetypes=[('Images','*.png *.jpg *.jpeg *.bmp *.gif'),('All','*.*')])
                    root.destroy()
                    if p: result.append(p)
                except Exception: pass
            self._tk_result = []
            self._tk_thread = threading.Thread(target=_pick, args=(self._tk_result,), daemon=True)
            self._tk_thread.start()

    def draw(self, surface):
        if self._tk_thread is not None and not self._tk_thread.is_alive():
            self._tk_thread = None
            if self._tk_result:
                path = self._tk_result.pop(); self._tk_result = None
                if path: self.image_path = path
        if self.image_path != self._preview_path:
            self._preview_path = self.image_path
            self._preview_surf = None
            if self.image_path:
                try:
                    import campaigns as _cm
                    resolved = _cm.resolve_image_path(self.image_path)
                    self._preview_surf = pygame.image.load(resolved).convert_alpha()
                except Exception: pass

        pygame.draw.rect(surface, PANEL_BG,     (self.x, self.y, self.W, self.H), border_radius=8)
        pygame.draw.rect(surface, PANEL_BORDER, (self.x, self.y, self.W, self.H), 2, border_radius=8)
        surface.blit(self.font.render('Edit Enemy', True, WHITE), (self.x + 12, self.y + 8))

        pygame.draw.rect(surface, (120, 30, 30), self.close_rect, border_radius=4)
        t = self.font.render('X', True, WHITE)
        surface.blit(t, (self.close_rect.centerx - t.get_width()//2,
                         self.close_rect.centery - t.get_height()//2))

        surface.blit(self.font.render('Name:', True, LIGHT_GRAY), (self.x + 12, self.y + 54))
        pygame.draw.rect(surface, TOOLBAR_BTN,  self.name_rect, border_radius=4)
        pygame.draw.rect(surface, PANEL_BORDER, self.name_rect, 1, border_radius=4)
        surface.blit(self.font.render(self.name_buf + '|', True, WHITE),
                     (self.name_rect.x + 6, self.name_rect.y + 6))

        surface.blit(self.font.render('Colour:', True, LIGHT_GRAY), (self.x + 12, self.y + 90))
        for i, (rect, (hex_c, _)) in enumerate(zip(self.color_rects, self.COLORS)):
            pygame.draw.rect(surface, pygame.Color(hex_c), rect, border_radius=4)
            if i == self.sel_color_idx:
                pygame.draw.rect(surface, WHITE, rect, 3, border_radius=4)

        preview_x = self.x + self.W - 56; preview_y = self.y + 140
        sel_color = pygame.Color(self.COLORS[self.sel_color_idx][0])
        sel_size  = self.SIZES[self.sel_size_idx][0]
        if self._preview_surf is not None:
            scaled = pygame.transform.scale(self._preview_surf, (sel_size * 2, sel_size * 2))
            surface.blit(scaled, (preview_x - sel_size, preview_y - sel_size))
        else:
            pygame.draw.circle(surface, sel_color, (preview_x, preview_y), sel_size)
        surface.blit(self.small_font.render('Preview', True, GRAY),
                     (preview_x - 22, preview_y + sel_size + 4))

        surface.blit(self.font.render('Size:', True, LIGHT_GRAY), (self.x + 12, self.y + 228))
        for i, (rect, (_, lbl)) in enumerate(zip(self.size_rects, self.SIZES)):
            bg = TOOLBAR_BTN_ACTIVE if i == self.sel_size_idx else TOOLBAR_BTN
            pygame.draw.rect(surface, bg, rect, border_radius=5)
            t = self.font.render(lbl, True, WHITE)
            surface.blit(t, (rect.centerx - t.get_width()//2, rect.centery - t.get_height()//2))

        surface.blit(self.font.render('Max HP:', True, LIGHT_GRAY), (self.x + 12, self.y + 354))
        pygame.draw.rect(surface, (80, 40, 40), self.hp_minus, border_radius=5)
        surface.blit(self.font.render('-', True, WHITE),
                     (self.hp_minus.centerx - 4, self.hp_minus.centery - 10))
        hp_t = self.font.render(str(self.max_hp), True, YELLOW)
        surface.blit(hp_t, (self.x + self.W//2 - hp_t.get_width()//2, self.y + 354))
        pygame.draw.rect(surface, (40, 80, 40), self.hp_plus, border_radius=5)
        surface.blit(self.font.render('+', True, WHITE),
                     (self.hp_plus.centerx - 4, self.hp_plus.centery - 10))

        surface.blit(self.font.render('Icon:', True, LIGHT_GRAY), (self.x + 12, self.y + 408))
        pygame.draw.rect(surface, TOOLBAR_BTN, self.browse_rect, border_radius=5)
        bt = self.font.render('Browse...', True, WHITE)
        surface.blit(bt, (self.browse_rect.centerx - bt.get_width()//2,
                          self.browse_rect.centery - bt.get_height()//2))
        fname = self.image_path.replace('\\','/').split('/')[-1] if self.image_path else 'None'
        surface.blit(self.small_font.render(fname[:28], True, LIGHT_GRAY), (self.x + 60, self.y + 412))

        pygame.draw.rect(surface, TOOLBAR_BTN, self.cancel_rect, border_radius=6)
        t = self.font.render('Cancel', True, WHITE)
        surface.blit(t, (self.cancel_rect.centerx - t.get_width()//2,
                         self.cancel_rect.centery - t.get_height()//2))
        pygame.draw.rect(surface, TOOLBAR_BTN_ACTIVE, self.confirm_rect, border_radius=6)
        t = self.font.render('Save Changes', True, WHITE)
        surface.blit(t, (self.confirm_rect.centerx - t.get_width()//2,
                         self.confirm_rect.centery - t.get_height()//2))

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE: return 'cancel'
            if event.key == pygame.K_RETURN: return self._result()
            if event.key == pygame.K_BACKSPACE: self.name_buf = self.name_buf[:-1]
            elif event.unicode and event.unicode.isprintable() and len(self.name_buf) < 30:
                self.name_buf += event.unicode
            return None
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return None
        pos = event.pos
        if self.close_rect.collidepoint(pos) or self.cancel_rect.collidepoint(pos):
            return 'cancel'
        if self.confirm_rect.collidepoint(pos): return self._result()
        for i, rect in enumerate(self.color_rects):
            if rect.collidepoint(pos): self.sel_color_idx = i; return None
        for i, rect in enumerate(self.size_rects):
            if rect.collidepoint(pos): self.sel_size_idx = i; return None
        if   self.hp_minus.collidepoint(pos): self.max_hp = max(1,   self.max_hp - 1)
        elif self.hp_plus.collidepoint(pos):  self.max_hp = min(999, self.max_hp + 1)
        elif self.browse_rect.collidepoint(pos): self._browse_image()
        return None

    def _result(self):
        return {
            'name':       self.name_buf.strip() or self.entity.name,
            'color':      self.COLORS[self.sel_color_idx][0],
            'size':       self.SIZES[self.sel_size_idx][0],
            'max_hp':     self.max_hp,
            'image_path': self.image_path,
        }


# ── Size popup ────────────────────────────────────────────────────────────────

class HintPopup:
    """Startup hint card with scrolling, newline support, and clickable URLs.
    handle_event() returns True when dismissed."""

    W   = 540
    PAD = 16
    _TITLE_H  = 40   # pixels reserved above content
    _FOOTER_H = 54   # pixels reserved below content (button + tip)
    _MARGIN   = 30   # min gap between dialog edge and screen edge
    _ACCENT  = (230, 200, 80)
    _URL_COL = (100, 190, 255)

    def __init__(self, font, small_font, screen_w, screen_h, hint_text):
        import re
        self.font        = font
        self.small_font  = small_font
        self.text        = hint_text
        self._url_re     = re.compile(r'(https?://\S+)')
        self._lh         = font.get_linesize()
        self._url_rects  = []
        self._scroll     = 0

        # Build lines before we know H so we can size to fit
        self._lines = self._build_lines(hint_text)

        # Ideal height: fit all lines; cap so dialog stays within screen
        max_h    = screen_h - self._MARGIN * 2
        ideal_h  = self._TITLE_H + len(self._lines) * self._lh + self._FOOTER_H
        H        = max(self._TITLE_H + self._lh + self._FOOTER_H,
                       min(ideal_h, max_h))

        self.x = (screen_w - self.W) // 2
        self.y = (screen_h - H) // 2

        self._content_y = self.y + self._TITLE_H
        self._content_h = H - self._TITLE_H - self._FOOTER_H
        self._vis_lines = max(1, self._content_h // self._lh)

        self._rect      = pygame.Rect(self.x, self.y, self.W, H)
        self._ok_rect   = pygame.Rect(self.x + self.W - self.PAD - 100,
                                      self.y + H - self.PAD - 34, 100, 34)
        self._up_rect   = pygame.Rect(self.x + self.W - self.PAD - 26,
                                      self.y + self._TITLE_H, 26, 26)
        self._down_rect = pygame.Rect(self.x + self.W - self.PAD - 26,
                                      self.y + H - self._FOOTER_H - 26, 26, 26)

    # ── Text parsing ─────────────────────────────────────────────────────────

    def _tokenize(self, text):
        """Return list of (token, is_url) for one paragraph."""
        tokens = []
        for part in self._url_re.split(text):
            if not part:
                continue
            if self._url_re.match(part):
                tokens.append((part, True))
            else:
                for word in part.split():
                    tokens.append((word, False))
        return tokens

    def _wrap_tokens(self, tokens, max_w):
        """Word-wrap token list into lines, each = [(token, is_url), ...]."""
        lines = []
        cur   = []
        cur_w = 0
        sp_w  = self.font.size(' ')[0]
        for tok, is_url in tokens:
            tw   = self.font.size(tok)[0]
            gap  = sp_w if cur else 0
            if cur and cur_w + gap + tw > max_w:
                lines.append(cur)
                cur   = [(tok, is_url)]
                cur_w = tw
            else:
                cur.append((tok, is_url))
                cur_w += gap + tw
        if cur:
            lines.append(cur)
        return lines

    def _build_lines(self, text):
        max_w = self.W - self.PAD * 2 - 30          # leave room for scroll arrows
        all_lines = []
        for para in text.split('\n'):
            if not para.strip():
                all_lines.append([])                 # blank line between paragraphs
            else:
                all_lines.extend(self._wrap_tokens(self._tokenize(para), max_w))
        return all_lines

    # ── Drawing ──────────────────────────────────────────────────────────────

    def draw(self, surface):
        self._url_rects = []

        pygame.draw.rect(surface, PANEL_BG,        self._rect, border_radius=10)
        pygame.draw.rect(surface, self._ACCENT,    self._rect, 2,  border_radius=10)

        title = self.font.render('Initial Message', True, self._ACCENT)
        surface.blit(title, (self.x + self.PAD, self.y + 10))

        # Clip content area
        clip = pygame.Rect(self.x + self.PAD, self._content_y,
                           self.W - self.PAD * 2 - 30, self._content_h)
        old_clip = surface.get_clip()
        surface.set_clip(clip)

        sp_w = self.font.size(' ')[0]
        ty   = self._content_y
        for line in self._lines[self._scroll: self._scroll + self._vis_lines]:
            tx = self.x + self.PAD
            for i, (tok, is_url) in enumerate(line):
                if i:
                    tx += sp_w
                col  = self._URL_COL if is_url else LIGHT_GRAY
                surf = self.font.render(tok, True, col)
                surface.blit(surf, (tx, ty))
                if is_url:
                    r = pygame.Rect(tx, ty, surf.get_width(), surf.get_height())
                    self._url_rects.append((r, tok))
                    pygame.draw.line(surface, self._URL_COL,
                                     (tx, ty + surf.get_height() - 1),
                                     (tx + surf.get_width(), ty + surf.get_height() - 1))
                tx += surf.get_width()
            ty += self._lh

        surface.set_clip(old_clip)

        # Scroll arrows (only when needed)
        total = len(self._lines)
        if total > self._vis_lines:
            can_up   = self._scroll > 0
            can_down = self._scroll + self._vis_lines < total
            for rect, sym, active in [
                (self._up_rect,   '▲', can_up),
                (self._down_rect, '▼', can_down),
            ]:
                bg = TOOLBAR_BTN_ACTIVE if active else TOOLBAR_BTN
                pygame.draw.rect(surface, bg, rect, border_radius=4)
                t = self.small_font.render(sym, True, WHITE if active else GRAY)
                surface.blit(t, (rect.centerx - t.get_width() // 2,
                                 rect.centery - t.get_height() // 2))

        # Footer
        pygame.draw.rect(surface, TOOLBAR_BTN_ACTIVE, self._ok_rect, border_radius=6)
        t = self.font.render('Got it', True, WHITE)
        surface.blit(t, (self._ok_rect.centerx - t.get_width() // 2,
                         self._ok_rect.centery - t.get_height() // 2))

        tip = self.small_font.render('Toggle: Campaign › Show initial message on load', True, GRAY)
        surface.blit(tip, (self.x + self.PAD, self.y + self._rect.h - self.PAD - 14))

    # ── Events ───────────────────────────────────────────────────────────────

    def _clamp_scroll(self):
        max_s = max(0, len(self._lines) - self._vis_lines)
        self._scroll = max(0, min(self._scroll, max_s))

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_RETURN, pygame.K_ESCAPE, pygame.K_SPACE):
                return True
            if event.key == pygame.K_UP:
                self._scroll -= 1; self._clamp_scroll()
            elif event.key == pygame.K_DOWN:
                self._scroll += 1; self._clamp_scroll()
            return False

        if event.type == pygame.MOUSEWHEEL:
            if self._rect.collidepoint(pygame.mouse.get_pos()):
                self._scroll -= event.y; self._clamp_scroll()
            return False

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            pos = event.pos
            # URL clicks
            for rect, url in self._url_rects:
                if rect.collidepoint(pos):
                    import webbrowser
                    webbrowser.open(url)
                    return False
            # Scroll arrows
            if self._up_rect.collidepoint(pos):
                self._scroll -= 1; self._clamp_scroll(); return False
            if self._down_rect.collidepoint(pos):
                self._scroll += 1; self._clamp_scroll(); return False
            # Dismiss
            if self._ok_rect.collidepoint(pos):
                return True
        return False


class SizePopup:
    """
    Compact horizontal bar of D&D size-category buttons.

    hit(pos) returns ('close', None) or ('size', radius_px) or (None, None).
    """

    BTN_W = 88; BTN_H = 52; GAP = 6; PAD = 10

    def __init__(self, entity, font, small_font, screen_w, screen_h):
        self.entity     = entity
        self.font       = font
        self.small_font = small_font
        n   = len(SIZE_PRESETS)
        self.W = n * self.BTN_W + (n - 1) * self.GAP + 2 * self.PAD
        self.H = self.BTN_H + 2 * self.PAD + 28   # 28 for title bar
        self.x = (screen_w - self.W) // 2
        self.y = (screen_h - self.H) // 3

        by = self.y + 28
        self.btns = [
            (pygame.Rect(self.x + self.PAD + i * (self.BTN_W + self.GAP),
                         by, self.BTN_W, self.BTN_H),
             size, lbl)
            for i, (size, lbl) in enumerate(SIZE_PRESETS)
        ]
        self.close_rect = pygame.Rect(self.x + self.W - 28, self.y + 4, 24, 22)

    def draw(self, surface):
        pygame.draw.rect(surface, PANEL_BG,
                         (self.x, self.y, self.W, self.H), border_radius=8)
        pygame.draw.rect(surface, PANEL_BORDER,
                         (self.x, self.y, self.W, self.H), 2, border_radius=8)

        title = self.font.render(f'Size - {self.entity.name}', True, WHITE)
        surface.blit(title, (self.x + self.PAD, self.y + 5))

        pygame.draw.rect(surface, (120, 30, 30), self.close_rect, border_radius=4)
        t = self.font.render('X', True, WHITE)
        surface.blit(t, (self.close_rect.centerx - t.get_width() // 2,
                         self.close_rect.centery - t.get_height() // 2))

        for rect, size, lbl in self.btns:
            active = (size == self.entity.size)
            bg = TOOLBAR_BTN_ACTIVE if active else TOOLBAR_BTN
            pygame.draw.rect(surface, bg, rect, border_radius=6)
            t = self.font.render(lbl, True, WHITE)
            surface.blit(t, (rect.centerx - t.get_width() // 2,
                             rect.centery - t.get_height() // 2 - 6))
            sub = self.small_font.render(f'r={size}px', True,
                                         LIGHT_GRAY if not active else WHITE)
            surface.blit(sub, (rect.centerx - sub.get_width() // 2,
                               rect.centery + 8))

    def hit(self, pos):
        if self.close_rect.collidepoint(pos):
            return ('close', None)
        for rect, size, _ in self.btns:
            if rect.collidepoint(pos):
                return ('size', size)
        return (None, None)


# ── GM Notes panel ────────────────────────────────────────────────────────────

class NotesPanel:
    """
    Left-side panel for per-scene freeform DM notes.

    Toggled by the Notes toolbar button.
    Click inside the text area to focus keyboard input.
    Click outside to unfocus (map controls resume).
    ✕ or re-clicking Notes in toolbar closes the panel.

    key(event) → True if text content changed (caller should persist to DB).
    """

    W       = 320   # panel width
    LINE_H  = 22    # pixels per text line
    PAD     = 10
    TITLE_H = 32    # height of the title bar

    def __init__(self, font, small_font):
        self.font        = font
        self.small_font  = small_font
        self.visible     = False
        self.focused     = False
        self.lines       = ['']   # logical lines (split on \n)
        self.cur_line    = 0
        self.cur_col     = 0
        self._scroll     = 0      # first visible line index
        self._max_lines  = 20     # updated each draw(); used by key()
        self._close_rect = None   # set during draw()

    # ── Text access ───────────────────────────────────────────────────────────

    @property
    def text(self):
        return '\n'.join(self.lines)

    def set_text(self, text):
        self.lines    = (text or '').split('\n') or ['']
        self.cur_line = len(self.lines) - 1
        self.cur_col  = len(self.lines[-1])
        self._scroll  = max(0, self.cur_line - self._max_lines + 1)

    # ── Hit testing ───────────────────────────────────────────────────────────

    def is_over(self, pos, screen_h):
        """True if pos is anywhere inside the panel."""
        return pygame.Rect(0, TOOLBAR_HEIGHT, self.W,
                           screen_h - TOOLBAR_HEIGHT).collidepoint(pos)

    def hit(self, pos):
        """Returns 'close', 'focus', or None (click outside panel)."""
        if self._close_rect and self._close_rect.collidepoint(pos):
            return 'close'
        if pygame.Rect(0, TOOLBAR_HEIGHT, self.W, 9999).collidepoint(pos):
            return 'focus'
        return None

    # ── Drawing ───────────────────────────────────────────────────────────────

    def draw(self, surface, screen_w, screen_h, scene_name=''):
        panel_h = screen_h - TOOLBAR_HEIGHT
        self._max_lines = max(1,
            (panel_h - self.TITLE_H - self.PAD * 2) // self.LINE_H)

        # Semi-transparent dark background
        overlay = pygame.Surface((self.W, panel_h), pygame.SRCALPHA)
        overlay.fill((20, 20, 40, 230))
        surface.blit(overlay, (0, TOOLBAR_HEIGHT))
        pygame.draw.rect(surface, PANEL_BORDER,
                         (0, TOOLBAR_HEIGHT, self.W, panel_h), 1)

        # Title bar
        pygame.draw.rect(surface, TOOLBAR_BG,
                         (0, TOOLBAR_HEIGHT, self.W, self.TITLE_H))
        label = f'Notes - {scene_name}' if scene_name else 'GM Notes'
        t = self.font.render(label, True, WHITE)
        surface.blit(t, (self.PAD, TOOLBAR_HEIGHT + (self.TITLE_H - t.get_height()) // 2))

        # Close ✕
        self._close_rect = pygame.Rect(self.W - 30, TOOLBAR_HEIGHT + 4, 26, 24)
        pygame.draw.rect(surface, (120, 30, 30), self._close_rect, border_radius=4)
        t = self.font.render('X', True, WHITE)
        surface.blit(t, (self._close_rect.centerx - t.get_width() // 2,
                         self._close_rect.centery - t.get_height() // 2))

        # Focus indicator: blue line under title when keyboard is captured
        if self.focused:
            pygame.draw.rect(surface, TOOLBAR_BTN_ACTIVE,
                             (0, TOOLBAR_HEIGHT + self.TITLE_H, self.W, 2))

        # Text rendering area (clip so nothing bleeds outside the panel)
        text_y0 = TOOLBAR_HEIGHT + self.TITLE_H + self.PAD
        clip    = pygame.Rect(self.PAD, text_y0,
                              self.W - self.PAD * 2,
                              panel_h - self.TITLE_H - self.PAD * 2)
        old_clip = surface.get_clip()
        surface.set_clip(clip)

        blink_on = (pygame.time.get_ticks() // 500) % 2 == 0
        visible  = self.lines[self._scroll: self._scroll + self._max_lines]

        for i, line in enumerate(visible):
            ly   = text_y0 + i * self.LINE_H
            lidx = i + self._scroll

            if line:
                t = self.font.render(line, True, LIGHT_GRAY)
                surface.blit(t, (self.PAD, ly))

            # Blinking cursor
            if lidx == self.cur_line and self.focused and blink_on:
                cx_px = self.PAD + self.font.size(line[:self.cur_col])[0]
                pygame.draw.line(surface, WHITE,
                                 (cx_px, ly), (cx_px, ly + self.LINE_H - 3), 2)

        surface.set_clip(old_clip)

        # Scroll bar (when content overflows)
        total = len(self.lines)
        if total > self._max_lines:
            bar_h   = panel_h - self.TITLE_H - self.PAD * 2
            thumb_h = max(16, bar_h * self._max_lines // total)
            thumb_y = (TOOLBAR_HEIGHT + self.TITLE_H + self.PAD
                       + (bar_h - thumb_h) * self._scroll
                       // max(1, total - self._max_lines))
            pygame.draw.rect(surface, PANEL_BORDER,
                             (self.W - 6, TOOLBAR_HEIGHT + self.TITLE_H + self.PAD,
                              4, bar_h), border_radius=2)
            pygame.draw.rect(surface, GRAY,
                             (self.W - 6, thumb_y, 4, thumb_h), border_radius=2)

    # ── Keyboard editing ──────────────────────────────────────────────────────

    def key(self, event):
        """
        Handle one KEYDOWN event.
        Returns True if text content changed (caller should save to DB).
        """
        ln = self.lines
        r, c = self.cur_line, self.cur_col
        changed = False

        if event.key == pygame.K_RETURN:
            rest   = ln[r][c:]
            ln[r]  = ln[r][:c]
            ln.insert(r + 1, rest)
            self.cur_line, self.cur_col = r + 1, 0
            changed = True

        elif event.key == pygame.K_BACKSPACE:
            if c > 0:
                ln[r] = ln[r][:c - 1] + ln[r][c:]
                self.cur_col -= 1
                changed = True
            elif r > 0:
                prev = len(ln[r - 1])
                ln[r - 1] += ln[r]
                ln.pop(r)
                self.cur_line, self.cur_col = r - 1, prev
                changed = True

        elif event.key == pygame.K_DELETE:
            if c < len(ln[r]):
                ln[r] = ln[r][:c] + ln[r][c + 1:]
                changed = True
            elif r < len(ln) - 1:
                ln[r] += ln[r + 1]
                ln.pop(r + 1)
                changed = True

        elif event.key == pygame.K_LEFT:
            if c > 0:
                self.cur_col -= 1
            elif r > 0:
                self.cur_line -= 1
                self.cur_col = len(ln[self.cur_line])

        elif event.key == pygame.K_RIGHT:
            if c < len(ln[r]):
                self.cur_col += 1
            elif r < len(ln) - 1:
                self.cur_line += 1
                self.cur_col = 0

        elif event.key == pygame.K_UP and r > 0:
            self.cur_line -= 1
            self.cur_col = min(c, len(ln[self.cur_line]))

        elif event.key == pygame.K_DOWN and r < len(ln) - 1:
            self.cur_line += 1
            self.cur_col = min(c, len(ln[self.cur_line]))

        elif event.key == pygame.K_HOME:
            self.cur_col = 0

        elif event.key == pygame.K_END:
            self.cur_col = len(ln[self.cur_line])

        elif event.unicode and event.unicode.isprintable():
            ln[r] = ln[r][:c] + event.unicode + ln[r][c:]
            self.cur_col += 1
            changed = True

        # Keep cursor inside the scroll window
        if self.cur_line < self._scroll:
            self._scroll = self.cur_line
        elif self.cur_line >= self._scroll + self._max_lines:
            self._scroll = self.cur_line - self._max_lines + 1

        return changed


# ── Stat block panel ──────────────────────────────────────────────────────────

class StatBlockPanel:
    """
    Floating panel showing AC, Speed, and the 6 D&D ability scores for a token.
    Values are adjusted with +/− buttons and auto-saved by the caller.
    Non-modal: stays visible while other map controls are used.

    hit(pos)  → ('close', None) | ('inc', field) | ('dec', field) | (None, None)
    adjust(field, delta) — clamps and updates self.data[field] in-place
    is_over(pos)         — True when pos falls inside the panel rectangle
    """

    W = 500; H = 252
    BTN = 26; PAD = 12; TITLE_H = 32

    SCORE_FIELDS = [
        ('str_score', 'STR'), ('dex_score', 'DEX'), ('con_score', 'CON'),
        ('int_score', 'INT'), ('wis_score', 'WIS'), ('cha_score', 'CHA'),
    ]
    FIELD_LIMITS = {
        'ac': (1, 30), 'speed': (0, 120),
        **{k: (1, 30) for k, _ in [
            ('str_score', ''), ('dex_score', ''), ('con_score', ''),
            ('int_score', ''), ('wis_score', ''), ('cha_score', ''),
        ]},
    }
    DEFAULTS = dict(ac=10, speed=30, str_score=10, dex_score=10,
                    con_score=10, int_score=10, wis_score=10, cha_score=10)

    def __init__(self, entity, data, font, small_font, screen_w, screen_h):
        self.entity = entity
        self.data   = {**self.DEFAULTS, **data}
        self.font   = font
        self.sf     = small_font
        self.x      = (screen_w - self.W) // 2
        self.y      = (screen_h - self.H) // 2
        self._dec   = {}   # field → pygame.Rect
        self._inc   = {}
        self._build()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _pm(self, lx, y, val_w=36):
        """Return (dec_rect, inc_rect) for a [-] value [+] triplet."""
        return (pygame.Rect(lx,             y, self.BTN, self.BTN),
                pygame.Rect(lx + self.BTN + val_w, y, self.BTN, self.BTN))

    def _build(self):
        bx, by = self.x, self.y
        p, B, T = self.PAD, self.BTN, self.TITLE_H

        self.close_rect = pygame.Rect(bx + self.W - B - 6, by + 3, B, 26)

        # AC / Speed row  (starts at by + T + 10)
        ay = by + T + 10
        self._dec['ac'],    self._inc['ac']    = self._pm(bx + p + 30, ay)
        self._dec['speed'], self._inc['speed'] = self._pm(bx + 272, ay, val_w=40)

        # Ability scores  3 cols × 2 rows starting at by + T + 10 + B + 34
        col_w = (self.W - 2 * p) // 3   # ≈ 158 px
        for i, (fld, _) in enumerate(self.SCORE_FIELDS):
            col, row = i % 3, i // 3
            cx = bx + p + col * col_w
            cy = by + T + 10 + B + 34 + row * 76
            self._dec[fld], self._inc[fld] = self._pm(cx + 8, cy + 20)

    # ── Drawing ───────────────────────────────────────────────────────────────

    def draw(self, surface):
        bx, by = self.x, self.y
        p, B, T = self.PAD, self.BTN, self.TITLE_H

        # Panel body
        pygame.draw.rect(surface, PANEL_BG,
                         (bx, by, self.W, self.H), border_radius=8)
        # Title bar
        pygame.draw.rect(surface, TOOLBAR_BG,
                         (bx, by, self.W, T), border_radius=8)
        pygame.draw.rect(surface, TOOLBAR_BG,
                         (bx, by + T // 2, self.W, T // 2))
        pygame.draw.rect(surface, PANEL_BORDER,
                         (bx, by, self.W, self.H), 2, border_radius=8)

        title = self.font.render(f'{self.entity.name} - Stat Block', True, WHITE)
        surface.blit(title, (bx + p, by + (T - title.get_height()) // 2))

        pygame.draw.rect(surface, (120, 30, 30), self.close_rect, border_radius=4)
        t = self.font.render('X', True, WHITE)
        surface.blit(t, (self.close_rect.centerx - t.get_width() // 2,
                         self.close_rect.centery - t.get_height() // 2))

        # AC / Speed row
        ay = by + T + 10
        surface.blit(self.font.render('AC:', True, LIGHT_GRAY), (bx + p, ay + 4))
        self._draw_pm(surface, 'ac', str(self.data['ac']))

        surface.blit(self.font.render('Speed:', True, LIGHT_GRAY), (bx + 208, ay + 4))
        self._draw_pm(surface, 'speed', str(self.data['speed']))
        surface.blit(self.sf.render('ft', True, GRAY),
                     (self._inc['speed'].right + 4, ay + 8))

        # Divider
        div_y = ay + B + 14
        pygame.draw.line(surface, PANEL_BORDER, (bx + p, div_y), (bx + self.W - p, div_y))

        # Ability scores
        col_w = (self.W - 2 * p) // 3
        for i, (fld, lbl) in enumerate(self.SCORE_FIELDS):
            col, row = i % 3, i // 3
            cx = bx + p + col * col_w
            cy = by + T + 10 + B + 34 + row * 76

            score = self.data.get(fld, 10)
            mod   = (score - 10) // 2
            mod_s = f'({mod:+d})'

            surface.blit(self.font.render(lbl, True, YELLOW), (cx + 8, cy))
            self._draw_pm(surface, fld, str(score))
            # Modifier to the right of [+]
            surface.blit(self.sf.render(mod_s, True, LIGHT_GRAY),
                         (self._inc[fld].right + 4, cy + 26))

        # Column dividers for the ability score grid
        for c in range(1, 3):
            lx = bx + p + c * col_w
            pygame.draw.line(surface, PANEL_BORDER,
                             (lx, div_y + 4), (lx, by + self.H - p), 1)

    def _draw_pm(self, surface, field, label):
        """Draw a [-] label [+] triplet for the given field."""
        d, i = self._dec[field], self._inc[field]
        pygame.draw.rect(surface, (80, 40, 40), d, border_radius=5)
        t = self.font.render('-', True, WHITE)
        surface.blit(t, (d.centerx - t.get_width()//2, d.centery - t.get_height()//2))

        mid_x = (d.right + i.left) // 2
        t = self.font.render(label, True, WHITE)
        surface.blit(t, (mid_x - t.get_width()//2,
                         d.y + (self.BTN - t.get_height()) // 2))

        pygame.draw.rect(surface, (40, 80, 40), i, border_radius=5)
        t = self.font.render('+', True, WHITE)
        surface.blit(t, (i.centerx - t.get_width()//2, i.centery - t.get_height()//2))

    # ── Interaction ───────────────────────────────────────────────────────────

    def hit(self, pos):
        """Returns ('close', None), ('inc', field), ('dec', field), or (None, None)."""
        if self.close_rect.collidepoint(pos):
            return ('close', None)
        for fld in self._dec:
            if self._dec[fld].collidepoint(pos):
                return ('dec', fld)
            if self._inc[fld].collidepoint(pos):
                return ('inc', fld)
        return (None, None)

    def adjust(self, field, delta):
        mn, mx = self.FIELD_LIMITS.get(field, (0, 999))
        self.data[field] = max(mn, min(mx, self.data.get(field, 10) + delta))

    def is_over(self, pos):
        return pygame.Rect(self.x, self.y, self.W, self.H).collidepoint(pos)


# ── Number-input popup (Damage / Heal) ────────────────────────────────────────

class NumberInputPopup:
    """
    Small modal popup that accepts a typed integer, used for Damage and Heal.
    mode: 'damage' | 'heal'
    """
    W = 320; H = 160

    def __init__(self, entity, mode, font, screen_w, screen_h):
        self.entity = entity
        self.mode   = mode
        self.value  = ''
        self.font   = font
        self.x = (screen_w - self.W) // 2
        self.y = (screen_h - self.H) // 2
        self._rect    = pygame.Rect(self.x, self.y, self.W, self.H)
        self._inp_r   = pygame.Rect(self.x + 16, self.y + 68, self.W - 32, 40)
        self._ok_r    = pygame.Rect(self.x + 16,           self.y + 118, 130, 34)
        self._cancel_r= pygame.Rect(self.x + self.W - 146, self.y + 118, 130, 34)

    def draw(self, surface):
        pygame.draw.rect(surface, PANEL_BG,     self._rect, border_radius=8)
        pygame.draw.rect(surface, PANEL_BORDER, self._rect, 2, border_radius=8)

        is_dmg  = self.mode == 'damage'
        accent  = (210, 55, 55) if is_dmg else (55, 190, 85)
        title   = ('Damage' if is_dmg else 'Heal') + f' - {self.entity.name}'
        t = self.font.render(title, True, accent)
        surface.blit(t, (self.x + 12, self.y + 12))

        hint = self.font.render('Enter amount:', True, LIGHT_GRAY)
        surface.blit(hint, (self.x + 16, self.y + 46))

        # Input field
        pygame.draw.rect(surface, (25, 28, 45), self._inp_r, border_radius=4)
        pygame.draw.rect(surface, accent,       self._inp_r, 1, border_radius=4)
        blink   = (pygame.time.get_ticks() // 500) % 2 == 0
        display = self.value + ('|' if blink else ' ')
        num_t   = pygame.font.Font(None, 38).render(display, True, WHITE)
        surface.blit(num_t, (self._inp_r.left + 10,
                             self._inp_r.centery - num_t.get_height() // 2))

        # OK button
        pygame.draw.rect(surface, accent, self._ok_r, border_radius=5)
        ok_t = self.font.render('OK', True, WHITE)
        surface.blit(ok_t, (self._ok_r.centerx - ok_t.get_width() // 2,
                            self._ok_r.centery - ok_t.get_height() // 2))

        # Cancel button
        pygame.draw.rect(surface, TOOLBAR_BTN, self._cancel_r, border_radius=5)
        cn_t = self.font.render('Cancel', True, WHITE)
        surface.blit(cn_t, (self._cancel_r.centerx - cn_t.get_width() // 2,
                            self._cancel_r.centery - cn_t.get_height() // 2))

    def hit(self, pos):
        """Returns ('confirm', int) | ('cancel', None) | (None, None)."""
        if self._ok_r.collidepoint(pos):
            return ('confirm', int(self.value) if self.value else 0)
        if self._cancel_r.collidepoint(pos):
            return ('cancel', None)
        return (None, None)

    def key(self, event):
        """Handle KEYDOWN. Returns same tuple as hit() or (None, None)."""
        if event.key == pygame.K_RETURN:
            return ('confirm', int(self.value) if self.value else 0)
        if event.key == pygame.K_ESCAPE:
            return ('cancel', None)
        if event.key == pygame.K_BACKSPACE:
            self.value = self.value[:-1]
        elif event.unicode.isdigit() and len(self.value) < 6:
            self.value += event.unicode
        return (None, None)


# ── Generic yes/no confirmation popup ────────────────────────────────────────

class ConfirmPopup:
    """Modal yes/no dialog. Returns True on confirm, False on cancel."""
    W = 380; H = 150

    def __init__(self, message, font, screen_w, screen_h):
        self.font = font
        self.x = (screen_w - self.W) // 2
        self.y = (screen_h - self.H) // 2
        self._rect     = pygame.Rect(self.x, self.y, self.W, self.H)
        self._yes_r    = pygame.Rect(self.x + 20,            self.y + 100, 155, 36)
        self._no_r     = pygame.Rect(self.x + self.W - 175,  self.y + 100, 155, 36)
        # Word-wrap the message to fit inside the panel
        words = message.split()
        self._lines = []
        line = ''
        for w in words:
            test = (line + ' ' + w).strip()
            if font.size(test)[0] <= self.W - 40:
                line = test
            else:
                if line:
                    self._lines.append(line)
                line = w
        if line:
            self._lines.append(line)

    def draw(self, surface):
        pygame.draw.rect(surface, PANEL_BG,     self._rect, border_radius=8)
        pygame.draw.rect(surface, PANEL_BORDER, self._rect, 2, border_radius=8)
        lh = self.font.get_linesize()
        ty = self.y + 20
        for ln in self._lines:
            t = self.font.render(ln, True, LIGHT_GRAY)
            surface.blit(t, (self.x + 20, ty))
            ty += lh
        pygame.draw.rect(surface, (180, 50, 50), self._yes_r, border_radius=5)
        yt = self.font.render('Yes, Remove', True, WHITE)
        surface.blit(yt, (self._yes_r.centerx - yt.get_width() // 2,
                          self._yes_r.centery - yt.get_height() // 2))
        pygame.draw.rect(surface, TOOLBAR_BTN, self._no_r, border_radius=5)
        nt = self.font.render('Cancel', True, WHITE)
        surface.blit(nt, (self._no_r.centerx - nt.get_width() // 2,
                          self._no_r.centery - nt.get_height() // 2))

    def hit(self, pos):
        """Returns True (confirmed), False (cancelled), or None (miss)."""
        if self._yes_r.collidepoint(pos):
            return True
        if self._no_r.collidepoint(pos):
            return False
        return None

    def key(self, event):
        if event.key in (pygame.K_RETURN, pygame.K_y):
            return True
        if event.key in (pygame.K_ESCAPE, pygame.K_n):
            return False
        return None


# ── Scene picker popup (for dropping scene markers) ───────────────────────────

class ScenePickerPopup:
    W      = 280
    BTN_H  = 38
    PAD    = 8
    TITLE_H = 40

    def __init__(self, scenes, current_scene_id, font, screen_w, screen_h):
        self.font    = font
        self.options = [(s[0], s[1]) for s in scenes if s[0] != current_scene_id]
        rows   = len(self.options)
        self.H = self.TITLE_H + rows * (self.BTN_H + self.PAD) + self.PAD
        self.x = (screen_w - self.W) // 2
        self.y = (screen_h - self.H) // 2
        self._close_r = pygame.Rect(self.x + self.W - 34, self.y + 6, 28, 28)
        self._btns = []
        by = self.y + self.TITLE_H + self.PAD
        for sid, sname in self.options:
            r = pygame.Rect(self.x + self.PAD, by, self.W - 2 * self.PAD, self.BTN_H)
            self._btns.append((sid, sname, r))
            by += self.BTN_H + self.PAD

    def draw(self, surface):
        pygame.draw.rect(surface, PANEL_BG,
                         (self.x, self.y, self.W, self.H), border_radius=8)
        pygame.draw.rect(surface, (0, 180, 160),
                         (self.x, self.y, self.W, self.H), 2, border_radius=8)
        t = self.font.render('Place marker to...', True, WHITE)
        surface.blit(t, (self.x + self.PAD, self.y + (self.TITLE_H - t.get_height()) // 2))
        pygame.draw.rect(surface, (120, 30, 30), self._close_r, border_radius=4)
        ct = self.font.render('X', True, WHITE)
        surface.blit(ct, (self._close_r.centerx - ct.get_width() // 2,
                          self._close_r.centery - ct.get_height() // 2))
        for _, sname, r in self._btns:
            pygame.draw.rect(surface, (30, 100, 95), r, border_radius=5)
            pygame.draw.rect(surface, (0, 180, 160), r, 1, border_radius=5)
            t = self.font.render(sname, True, WHITE)
            surface.blit(t, (r.x + 10, r.centery - t.get_height() // 2))

    def hit(self, pos):
        """Returns ('select', scene_id) | ('close', None) | (None, None)."""
        if self._close_r.collidepoint(pos):
            return 'close', None
        for sid, _, r in self._btns:
            if r.collidepoint(pos):
                return 'select', sid
        if not pygame.Rect(self.x, self.y, self.W, self.H).collidepoint(pos):
            return 'close', None
        return None, None


# ── Sound Zone dialog ─────────────────────────────────────────────────────────

ZONE_PALETTE = [
    ('#4488ff', 'Blue'),
    ('#44cc66', 'Green'),
    ('#cc44cc', 'Purple'),
    ('#ff8822', 'Orange'),
    ('#ff4444', 'Red'),
    ('#ffcc22', 'Yellow'),
]


class SoundZoneDialog:
    """Modal form shown after dragging a zone rectangle.  Returns zone data or None."""
    W = 500; H = 320
    PAD = 16

    def __init__(self, x, y, w, h, font, screen_w, screen_h, prefill=None):
        self.zone_x, self.zone_y = x, y
        self.zone_w, self.zone_h = w, h
        self.font   = font
        self.result = None

        # Editable fields
        pf = prefill or {}
        self.name_buf  = pf.get('name', 'New Zone')
        self.track_buf = pf.get('track', '')
        self.color     = pf.get('color', ZONE_PALETTE[0][0])
        self._name_focus  = True
        self._track_focus = False

        self.bx = (screen_w - self.W) // 2
        self.by = (screen_h - self.H) // 2
        self._build_rects()

    def _build_rects(self):
        bx, by, P = self.bx, self.by, self.PAD
        self._name_r   = pygame.Rect(bx + P,                by + 60,  self.W - P*2, 38)
        self._track_r  = pygame.Rect(bx + P,                by + 124, self.W - P*2, 38)
        swatch_y       = by + 210
        self._tta_r    = pygame.Rect(bx + self.W - P - 110, swatch_y, 110,          26)
        self._swatch_r = [pygame.Rect(bx + P + i * 44, swatch_y, 36, 26)
                          for i in range(len(ZONE_PALETTE))]
        self._ok_r     = pygame.Rect(bx + self.W - P - 110, by + self.H - P - 34, 110, 34)
        self._cancel_r = pygame.Rect(bx + P,                by + self.H - P - 34,  90, 34)
        self._close_r  = pygame.Rect(bx + self.W - P - 28,  by + 8,                28, 28)

    def handle_event(self, ev):
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            pos = ev.pos
            if self._close_r.collidepoint(pos) or self._cancel_r.collidepoint(pos):
                self.result = None; return 'close'
            if self._ok_r.collidepoint(pos):
                return self._confirm()
            for i, sr in enumerate(self._swatch_r):
                if sr.collidepoint(pos):
                    self.color = ZONE_PALETTE[i][0]; return None
            if self._tta_r.collidepoint(pos):
                return 'browse_tta'
            if self._name_r.collidepoint(pos):
                self._name_focus = True;  self._track_focus = False
            elif self._track_r.collidepoint(pos):
                self._track_focus = True; self._name_focus  = False
            else:
                self._name_focus = self._track_focus = False

        elif ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_ESCAPE:
                self.result = None; return 'close'
            if ev.key == pygame.K_RETURN:
                return self._confirm()
            if ev.key == pygame.K_TAB:
                self._name_focus, self._track_focus = self._track_focus, self._name_focus
                return None
            buf_attr = '_name_buf' if self._name_focus else '_track_buf' if self._track_focus else None
            if buf_attr:
                buf = getattr(self, buf_attr[1:])
                ctrl = ev.mod & pygame.KMOD_CTRL
                if ctrl and ev.key == pygame.K_v:
                    clip = _read_clipboard().strip()
                    if clip:
                        setattr(self, buf_attr[1:], clip[:300])
                elif ctrl and ev.key == pygame.K_a:
                    setattr(self, buf_attr[1:], '')
                elif ev.key == pygame.K_BACKSPACE:
                    setattr(self, buf_attr[1:], buf[:-1])
                elif ev.unicode and len(buf) < 300:
                    setattr(self, buf_attr[1:], buf + ev.unicode)
        return None

    def set_track(self, url):
        """Populate the track field (called by the TTA browser when a track is selected)."""
        self.track_buf    = url
        self._track_focus = True
        self._name_focus  = False

    def _confirm(self):
        name = self.name_buf.strip() or 'Zone'
        self.result = {
            'name': name, 'track': self.track_buf.strip(),
            'color': self.color,
            'x': self.zone_x, 'y': self.zone_y,
            'w': self.zone_w, 'h': self.zone_h,
        }
        return 'confirm'

    def draw(self, surface):
        dim = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 140))
        surface.blit(dim, (0, 0))

        bx, by, P = self.bx, self.by, self.PAD
        box = pygame.Rect(bx, by, self.W, self.H)
        pygame.draw.rect(surface, (22, 30, 50), box, border_radius=10)
        pygame.draw.rect(surface, (40, 100, 160), box, 2, border_radius=10)

        title = self.font.render('New Sound Zone', True, (140, 200, 255))
        surface.blit(title, (bx + P, by + 12))

        pygame.draw.rect(surface, (130, 40, 40), self._close_r, border_radius=4)
        xl = self.font.render('X', True, WHITE)
        surface.blit(xl, (self._close_r.centerx - xl.get_width()//2,
                          self._close_r.centery - xl.get_height()//2))

        # Name field
        nl = self.font.render('Name:', True, LIGHT_GRAY)
        surface.blit(nl, (bx + P, by + 44))
        bc = (80, 160, 220) if self._name_focus else (60, 70, 90)
        pygame.draw.rect(surface, (25, 30, 50), self._name_r, border_radius=4)
        pygame.draw.rect(surface, bc, self._name_r, 1, border_radius=4)
        blink = (pygame.time.get_ticks() // 500) % 2 == 0
        nt = self.font.render(self.name_buf + ('|' if self._name_focus and blink else ''), True, WHITE)
        surface.blit(nt, (self._name_r.x + 8, self._name_r.centery - nt.get_height()//2))

        # Track field
        tl = self.font.render('Track:', True, LIGHT_GRAY)
        surface.blit(tl, (bx + P, by + 108))
        bc2 = (80, 160, 220) if self._track_focus else (60, 70, 90)
        pygame.draw.rect(surface, (25, 30, 50), self._track_r, border_radius=4)
        pygame.draw.rect(surface, bc2, self._track_r, 1, border_radius=4)
        track_disp = self.track_buf[-55:] if len(self.track_buf) > 55 else self.track_buf
        tt = self.font.render(track_disp + ('|' if self._track_focus and blink else ''), True, (180, 220, 180))
        surface.blit(tt, (self._track_r.x + 8, self._track_r.centery - tt.get_height()//2))

        # Source hint below track field
        hint = self.font.render('Spotify  ·  Tabletop Audio  ·  local .mp3 / .ogg / .wav', True, (90, 115, 145))
        surface.blit(hint, (bx + P, by + 170))

        # Color label + swatches + Browse TTA button (all on same row)
        cl = self.font.render('Color:', True, LIGHT_GRAY)
        surface.blit(cl, (bx + P, by + 194))
        for i, (hex_col, _) in enumerate(ZONE_PALETTE):
            sr = self._swatch_r[i]
            h = hex_col.lstrip('#'); r,g,b = int(h[0:2],16),int(h[2:4],16),int(h[4:6],16)
            pygame.draw.rect(surface, (r, g, b), sr, border_radius=4)
            if hex_col == self.color:
                pygame.draw.rect(surface, WHITE, sr, 2, border_radius=4)
        pygame.draw.rect(surface, (30, 70, 110), self._tta_r, border_radius=4)
        pygame.draw.rect(surface, (80, 160, 220), self._tta_r, 1, border_radius=4)
        tta_t = self.font.render('Browse TTA', True, (160, 210, 255))
        surface.blit(tta_t, (self._tta_r.centerx - tta_t.get_width()//2,
                             self._tta_r.centery - tta_t.get_height()//2))

        # Buttons
        pygame.draw.rect(surface, (40, 100, 60), self._ok_r, border_radius=5)
        ok_t = self.font.render('Create Zone', True, WHITE)
        surface.blit(ok_t, (self._ok_r.centerx - ok_t.get_width()//2,
                            self._ok_r.centery - ok_t.get_height()//2))
        pygame.draw.rect(surface, TOOLBAR_BTN, self._cancel_r, border_radius=5)
        cn_t = self.font.render('Cancel', True, WHITE)
        surface.blit(cn_t, (self._cancel_r.centerx - cn_t.get_width()//2,
                            self._cancel_r.centery - cn_t.get_height()//2))


# ── Tabletop Audio browser ────────────────────────────────────────────────────

class TabletopAudioBrowserDialog:
    """Searchable, scrollable list of Tabletop Audio tracks with preview. Returns CDN URL."""
    W, H, PAD = 520, 540, 14
    ROW_H = 34

    def __init__(self, font, screen_w, screen_h, stop_audio=None, play_audio=None):
        self.font            = font
        self.bx              = (screen_w - self.W) // 2
        self.by              = (screen_h - self.H) // 2
        self._search         = ''
        self._scroll         = 0
        self._tracks         = []
        self._loading        = True
        self._selected       = None   # absolute index in filtered list
        self._stop_audio     = stop_audio   # callable to silence zone audio before preview
        self._play_audio     = play_audio   # callable(url) to start preview via pygame
        self._last_click_t   = 0
        self._last_click_idx = -1
        self._site_link_r    = None   # set during draw()
        self._build_rects()

    def _build_rects(self):
        bx, by, P = self.bx, self.by, self.PAD
        self._close_r   = pygame.Rect(bx + self.W - P - 28,  by + 8,               28,  28)
        self._search_r  = pygame.Rect(bx + P,                by + 46,  self.W - P*2,    30)
        self._list_top  = by + 86
        btn_y           = by + self.H - P - 34
        self._list_bot  = btn_y - 38   # 38 px: scroll-hint line + gap above buttons
        self._list_h    = self._list_bot - self._list_top
        self._preview_r = pygame.Rect(bx + P,                btn_y,  84, 34)
        self._stop_r    = pygame.Rect(bx + P + 92,           btn_y,  64, 34)
        self._cancel_r  = pygame.Rect(bx + self.W - P - 202, btn_y,  90, 34)
        self._select_r  = pygame.Rect(bx + self.W - P - 110, btn_y, 110, 34)

    def update_songlist(self, songlist):
        self._loading  = False
        self._selected = None
        self._tracks   = sorted(
            [(n, d['title'], d['url']) for n, d in songlist.items()],
            key=lambda x: x[0])
        self._scroll = 0

    def _filtered(self):
        q = self._search.lower()
        return [(n, t, u) for n, t, u in self._tracks if not q or q in t.lower()]

    def _start_preview(self, url):
        if self._stop_audio:
            self._stop_audio()
        if self._play_audio:
            self._play_audio(url)

    def _stop_preview(self):
        if self._stop_audio:
            self._stop_audio()

    def handle_event(self, ev):
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            pos = ev.pos
            if self._close_r.collidepoint(pos) or self._cancel_r.collidepoint(pos):
                self._stop_preview(); return 'close'
            if self._site_link_r and self._site_link_r.collidepoint(pos):
                import webbrowser
                webbrowser.open('https://tabletopaudio.com')
                return None
            if self._select_r.collidepoint(pos) and self._selected is not None:
                filtered = self._filtered()
                if 0 <= self._selected < len(filtered):
                    self._stop_preview(); return filtered[self._selected][2]
            if self._preview_r.collidepoint(pos) and self._selected is not None:
                filtered = self._filtered()
                if 0 <= self._selected < len(filtered):
                    self._start_preview(filtered[self._selected][2])
            if self._stop_r.collidepoint(pos):
                self._stop_preview()
            if not self._loading:
                filtered     = self._filtered()
                visible_rows = self._list_h // self.ROW_H
                now          = pygame.time.get_ticks()
                for i in range(min(visible_rows, len(filtered) - self._scroll)):
                    abs_i = self._scroll + i
                    ry    = self._list_top + i * self.ROW_H
                    if pygame.Rect(self.bx + self.PAD, ry, self.W - self.PAD*2,
                                   self.ROW_H - 2).collidepoint(pos):
                        if abs_i == self._last_click_idx and now - self._last_click_t < 500:
                            self._stop_preview()
                            return filtered[abs_i][2]
                        self._selected       = abs_i
                        self._last_click_idx = abs_i
                        self._last_click_t   = now
                        break

        elif ev.type == pygame.MOUSEWHEEL:
            if not self._loading:
                filtered     = self._filtered()
                visible_rows = self._list_h // self.ROW_H
                max_scroll   = max(0, len(filtered) - visible_rows)
                self._scroll = max(0, min(max_scroll, self._scroll - ev.y))

        elif ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_ESCAPE:
                self._stop_preview(); return 'close'
            if ev.key == pygame.K_RETURN and self._selected is not None:
                filtered = self._filtered()
                if 0 <= self._selected < len(filtered):
                    self._stop_preview(); return filtered[self._selected][2]
            elif ev.key == pygame.K_BACKSPACE:
                self._search = self._search[:-1]; self._scroll = 0; self._selected = None
            elif ev.unicode and ev.key not in (pygame.K_RETURN,) and len(self._search) < 60:
                self._search += ev.unicode; self._scroll = 0; self._selected = None

        return None

    def draw(self, surface):
        dim = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 160))
        surface.blit(dim, (0, 0))

        bx, by, P = self.bx, self.by, self.PAD
        pygame.draw.rect(surface, (18, 26, 44), pygame.Rect(bx, by, self.W, self.H), border_radius=10)
        pygame.draw.rect(surface, (40, 100, 160), pygame.Rect(bx, by, self.W, self.H), 2, border_radius=10)

        tl = self.font.render('Tabletop Audio  -  Browse Tracks', True, (140, 200, 255))
        surface.blit(tl, (bx + P, by + 12))

        # "Try the site!" link — left of the X button
        ll_surf = self.font.render('Try the site!', True, (80, 160, 255))
        ll_x = self._close_r.left - 12 - ll_surf.get_width()
        ll_y = by + 12
        self._site_link_r = pygame.Rect(ll_x, ll_y, ll_surf.get_width(), ll_surf.get_height())
        surface.blit(ll_surf, (ll_x, ll_y))
        pygame.draw.line(surface, (80, 160, 255),
                         (ll_x, ll_y + ll_surf.get_height()),
                         (ll_x + ll_surf.get_width(), ll_y + ll_surf.get_height()), 1)

        pygame.draw.rect(surface, (130, 40, 40), self._close_r, border_radius=4)
        xl = self.font.render('X', True, WHITE)
        surface.blit(xl, (self._close_r.centerx - xl.get_width()//2,
                          self._close_r.centery - xl.get_height()//2))

        sl = self.font.render('Search:', True, LIGHT_GRAY)
        surface.blit(sl, (bx + P, by + 32))
        pygame.draw.rect(surface, (25, 30, 50), self._search_r, border_radius=4)
        pygame.draw.rect(surface, (80, 160, 220), self._search_r, 1, border_radius=4)
        blink = (pygame.time.get_ticks() // 500) % 2 == 0
        st = self.font.render(self._search + ('|' if blink else ''), True, WHITE)
        surface.blit(st, (self._search_r.x + 8, self._search_r.centery - st.get_height()//2))

        if self._loading:
            ll = self.font.render('Loading track list from tabletopaudio.com...', True, LIGHT_GRAY)
            surface.blit(ll, (bx + P, self._list_top + 10))
        else:
            filtered     = self._filtered()
            visible_rows = self._list_h // self.ROW_H

            # Count placed after "Search:" label — clear of the X button
            cnt = self.font.render(f'({len(filtered)} tracks)', True, (100, 130, 160))
            surface.blit(cnt, (bx + P + sl.get_width() + 8, by + 32))

            for i in range(min(visible_rows, len(filtered) - self._scroll)):
                abs_i       = self._scroll + i
                n, title, _ = filtered[abs_i]
                ry          = self._list_top + i * self.ROW_H
                row         = pygame.Rect(bx + P, ry, self.W - P*2, self.ROW_H - 2)
                if abs_i == self._selected:
                    pygame.draw.rect(surface, (45, 95, 175), row, border_radius=3)
                else:
                    pygame.draw.rect(surface, (30, 40, 65) if i % 2 == 0 else (25, 33, 55),
                                     row, border_radius=3)
                num_s = self.font.render(f'{n:>4}', True, (100, 130, 160))
                ttl_c = (220, 240, 255) if abs_i == self._selected else WHITE
                ttl_s = self.font.render(title, True, ttl_c)
                cy    = ry + (self.ROW_H - num_s.get_height()) // 2
                surface.blit(num_s, (bx + P + 4,  cy))
                surface.blit(ttl_s, (bx + P + 50, cy))

            if len(filtered) > visible_rows:
                hi = min(self._scroll + visible_rows, len(filtered))
                sc = self.font.render(
                    f'({self._scroll + 1}-{hi} of {len(filtered)})  scroll or type to filter',
                    True, (70, 90, 110))
                surface.blit(sc, (bx + P, self._list_bot + 4))

        # Bottom buttons
        is_playing = pygame.mixer.music.get_busy()
        has_sel    = self._selected is not None

        pygame.draw.rect(surface, (30, 100, 50) if has_sel else (25, 45, 30),
                         self._preview_r, border_radius=5)
        pt = self.font.render('Preview', True, WHITE if has_sel else (80, 110, 80))
        surface.blit(pt, (self._preview_r.centerx - pt.get_width()//2,
                          self._preview_r.centery - pt.get_height()//2))

        pygame.draw.rect(surface, (130, 40, 40) if is_playing else (50, 30, 30),
                         self._stop_r, border_radius=5)
        stt = self.font.render('Stop', True, WHITE if is_playing else (100, 70, 70))
        surface.blit(stt, (self._stop_r.centerx - stt.get_width()//2,
                           self._stop_r.centery - stt.get_height()//2))

        pygame.draw.rect(surface, TOOLBAR_BTN, self._cancel_r, border_radius=5)
        cn = self.font.render('Cancel', True, WHITE)
        surface.blit(cn, (self._cancel_r.centerx - cn.get_width()//2,
                          self._cancel_r.centery - cn.get_height()//2))

        pygame.draw.rect(surface, (40, 100, 60) if has_sel else (25, 45, 30),
                         self._select_r, border_radius=5)
        slt = self.font.render('Select Track', True, WHITE if has_sel else (80, 110, 80))
        surface.blit(slt, (self._select_r.centerx - slt.get_width()//2,
                           self._select_r.centery - slt.get_height()//2))


# ── PIN lock helpers ──────────────────────────────────────────────────────────

def _draw_pin_dots(surface, font, cx, top_y, entered, n_slots=6):
    n = max(len(entered), n_slots)
    spacing = 26
    x0 = cx - (n - 1) * spacing // 2
    for i in range(n):
        sx = x0 + i * spacing
        if i < len(entered):
            pygame.draw.circle(surface, WHITE, (sx, top_y + 10), 9)
        else:
            pygame.draw.circle(surface, (55, 75, 100), (sx, top_y + 10), 9, 2)


def _draw_numpad(surface, font, keys, bw, bh):
    for lbl, kx, ky in keys:
        r = pygame.Rect(kx, ky, bw, bh)
        if lbl in ('OK', 'ENTER'):
            col = (35, 110, 50)
        elif lbl == 'CLR':
            col = (120, 35, 35)
        else:
            col = (38, 52, 84)
        pygame.draw.rect(surface, col, r, border_radius=7)
        pygame.draw.rect(surface, (65, 80, 120), r, 1, border_radius=7)
        lt = font.render(lbl, True, WHITE)
        surface.blit(lt, (r.centerx - lt.get_width()//2,
                          r.centery - lt.get_height()//2))


# ── PIN setup dialog ──────────────────────────────────────────────────────────

class PinSetupDialog:
    """Two-phase numpad dialog for setting the lock PIN. Returns ('set_pin', pin) on success."""
    W, H, PAD = 330, 440, 20
    _BW, _BH, _BG = 88, 68, 6

    def __init__(self, font, screen_w, screen_h):
        self.font   = font
        self.bx     = (screen_w - self.W) // 2
        self.by     = (screen_h - self.H) // 2
        self._phase = 1
        self._pin1  = ''
        self._input = ''
        self._error = ''
        self._build_rects()

    def _build_rects(self):
        bx, by = self.bx, self.by
        bw, bh, bg = self._BW, self._BH, self._BG
        self._close_r = pygame.Rect(bx + self.W - self.PAD - 28, by + 8, 28, 28)
        nx = bx + (self.W - 3*bw - 2*bg) // 2
        ny = by + 128
        self._keys = [
            ('1', nx,           ny),          ('2', nx+bw+bg,     ny),
            ('3', nx+2*(bw+bg), ny),          ('4', nx,           ny+bh+bg),
            ('5', nx+bw+bg,     ny+bh+bg),    ('6', nx+2*(bw+bg), ny+bh+bg),
            ('7', nx,           ny+2*(bh+bg)),('8', nx+bw+bg,     ny+2*(bh+bg)),
            ('9', nx+2*(bw+bg), ny+2*(bh+bg)),('CLR', nx,         ny+3*(bh+bg)),
            ('0', nx+bw+bg,     ny+3*(bh+bg)),('OK',  nx+2*(bw+bg), ny+3*(bh+bg)),
        ]
        self._key_r = {lbl: pygame.Rect(x, y, bw, bh) for lbl, x, y in self._keys}

    def handle_event(self, ev):
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            pos = ev.pos
            if self._close_r.collidepoint(pos):
                return 'cancel'
            for lbl, r in self._key_r.items():
                if r.collidepoint(pos):
                    return self._tap(lbl)
        elif ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_ESCAPE:
                return 'cancel'
            if ev.unicode.isdigit():
                return self._tap(ev.unicode)
            if ev.key == pygame.K_BACKSPACE:
                self._input = self._input[:-1]
            if ev.key == pygame.K_RETURN:
                return self._tap('OK')
        return None

    def _tap(self, lbl):
        if lbl.isdigit():
            if len(self._input) < 8: self._input += lbl
            self._error = ''
        elif lbl == 'CLR':
            self._input = self._input[:-1]; self._error = ''
        elif lbl == 'OK':
            if not self._input:
                self._error = 'Enter at least 1 digit'; return None
            if self._phase == 1:
                self._pin1 = self._input; self._input = ''; self._phase = 2
            else:
                if self._input == self._pin1:
                    return ('set_pin', self._pin1)
                self._error = 'PINs do not match — try again'
                self._input = ''; self._phase = 1; self._pin1 = ''
        return None

    def draw(self, surface):
        dim = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 160))
        surface.blit(dim, (0, 0))
        bx, by = self.bx, self.by
        box = pygame.Rect(bx, by, self.W, self.H)
        pygame.draw.rect(surface, (18, 26, 44), box, border_radius=10)
        pygame.draw.rect(surface, (40, 100, 160), box, 2, border_radius=10)

        tl = self.font.render('Setup Lock PIN', True, (140, 200, 255))
        surface.blit(tl, (bx + self.W//2 - tl.get_width()//2, by + 12))

        pygame.draw.rect(surface, (130, 40, 40), self._close_r, border_radius=4)
        xl = self.font.render('X', True, WHITE)
        surface.blit(xl, (self._close_r.centerx - xl.get_width()//2,
                          self._close_r.centery - xl.get_height()//2))

        phase_lbl = 'Enter new PIN:' if self._phase == 1 else 'Confirm PIN:'
        pl = self.font.render(phase_lbl, True, LIGHT_GRAY)
        surface.blit(pl, (bx + self.W//2 - pl.get_width()//2, by + 48))

        _draw_pin_dots(surface, self.font, bx + self.W//2, by + 76, self._input)

        if self._error:
            et = self.font.render(self._error, True, (220, 80, 80))
            surface.blit(et, (bx + self.W//2 - et.get_width()//2, by + 106))

        _draw_numpad(surface, self.font, self._keys, self._BW, self._BH)


# ── Lock overlay ──────────────────────────────────────────────────────────────

class LockOverlay:
    """Full-screen lock screen. Cannot be dismissed without the correct PIN."""
    W, H = 330, 440
    _BW, _BH, _BG = 88, 68, 6

    def __init__(self, font, screen_w, screen_h):
        self.font   = font
        self._sw    = screen_w
        self._sh    = screen_h
        self.bx     = (screen_w  - self.W) // 2
        self.by     = (screen_h - self.H) // 2
        self._input = ''
        self._error = ''
        self._build_rects()

    def _build_rects(self):
        bx, by = self.bx, self.by
        bw, bh, bg = self._BW, self._BH, self._BG
        nx = bx + (self.W - 3*bw - 2*bg) // 2
        ny = by + 132
        self._keys = [
            ('1', nx,           ny),          ('2', nx+bw+bg,     ny),
            ('3', nx+2*(bw+bg), ny),          ('4', nx,           ny+bh+bg),
            ('5', nx+bw+bg,     ny+bh+bg),    ('6', nx+2*(bw+bg), ny+bh+bg),
            ('7', nx,           ny+2*(bh+bg)),('8', nx+bw+bg,     ny+2*(bh+bg)),
            ('9', nx+2*(bw+bg), ny+2*(bh+bg)),('CLR',   nx,           ny+3*(bh+bg)),
            ('0', nx+bw+bg,     ny+3*(bh+bg)),('ENTER', nx+2*(bw+bg), ny+3*(bh+bg)),
        ]
        self._key_r = {lbl: pygame.Rect(x, y, bw, bh) for lbl, x, y in self._keys}

    def wrong_pin(self):
        self._error = 'Incorrect PIN'
        self._input = ''

    def handle_event(self, ev):
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            for lbl, r in self._key_r.items():
                if r.collidepoint(ev.pos):
                    return self._tap(lbl)
        elif ev.type == pygame.KEYDOWN:
            if ev.unicode.isdigit():
                return self._tap(ev.unicode)
            if ev.key == pygame.K_BACKSPACE:
                self._input = self._input[:-1]
            if ev.key == pygame.K_RETURN:
                return self._tap('ENTER')
        return None

    def _tap(self, lbl):
        if lbl.isdigit():
            if len(self._input) < 8: self._input += lbl
            self._error = ''
        elif lbl == 'CLR':
            self._input = self._input[:-1]; self._error = ''
        elif lbl == 'ENTER':
            if self._input:
                pin = self._input; self._input = ''; return pin
        return None

    def draw(self, surface):
        dim = pygame.Surface((self._sw, self._sh), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 220))
        surface.blit(dim, (0, 0))
        bx, by = self.bx, self.by
        box = pygame.Rect(bx, by, self.W, self.H)
        pygame.draw.rect(surface, (12, 18, 34), box, border_radius=12)
        pygame.draw.rect(surface, (60, 120, 200), box, 2, border_radius=12)

        tl = self.font.render('[ LOCKED ]', True, (200, 160, 50))
        surface.blit(tl, (bx + self.W//2 - tl.get_width()//2, by + 18))

        sub = self.font.render('Enter PIN to unlock', True, LIGHT_GRAY)
        surface.blit(sub, (bx + self.W//2 - sub.get_width()//2, by + 52))

        _draw_pin_dots(surface, self.font, bx + self.W//2, by + 82, self._input)

        if self._error:
            et = self.font.render(self._error, True, (230, 80, 80))
            surface.blit(et, (bx + self.W//2 - et.get_width()//2, by + 110))

        _draw_numpad(surface, self.font, self._keys, self._BW, self._BH)


# ── Campaign dialog ────────────────────────────────────────────────────────────

class CampaignDialog:
    """Modal dialog for campaign selection, creation, renaming, and deletion."""
    W = 480

    ITEM_H   = 38
    ITEM_GAP = 6
    PAD      = 16

    def __init__(self, campaigns, active, font, screen_w, screen_h,
                 hints_map=None):
        self.campaigns  = list(campaigns)
        self.active     = active
        self.font       = font
        self.selected   = active
        self.name_buf   = ''        # new-campaign input
        self.rename_buf = ''        # rename input
        self._typing    = False     # new-campaign input focused
        self._rtyping   = False     # rename input focused
        self.hints_map  = hints_map or {c: True for c in campaigns}
        self.result     = None

        visible_items = min(len(self.campaigns), 6)
        list_h = visible_items * (self.ITEM_H + self.ITEM_GAP)
        # All rows laid out top-to-bottom; compute exact height so nothing overlaps
        self.H = (self.PAD + 30 +   # title bar
                  list_h + self.PAD +  # campaign list + gap
                  36 + 10 +            # create row + gap
                  36 + 16 +            # rename row + gap
                  26 + 14 +            # hints checkbox + gap
                  32 + self.PAD)       # switch button + bottom padding

        self.bx = (screen_w - self.W) // 2
        self.by = (screen_h - self.H) // 2
        self._build_rects()

    @property
    def hints_enabled(self):
        """Always reflects the selected campaign's stored value."""
        return self.hints_map.get(self.selected, True)

    def _build_rects(self):
        bx, by = self.bx, self.by
        P, IH, IG = self.PAD, self.ITEM_H, self.ITEM_GAP
        self._close_r = pygame.Rect(bx + self.W - P - 28, by + 8, 28, 28)

        # Campaign list (top-down)
        y = by + P + 30
        self._item_rects = []
        self._del_rects  = []
        for _ in self.campaigns:
            ir = pygame.Rect(bx + P, y, self.W - P*2 - 54, IH)
            dr = pygame.Rect(bx + self.W - P - 48, y, 48, IH)
            self._item_rects.append(ir)
            self._del_rects.append(dr)
            y += IH + IG
        y += P  # gap between list and create row

        # Create row
        self._input_rect  = pygame.Rect(bx + P, y, self.W - P*2 - 90, 36)
        self._create_rect = pygame.Rect(bx + self.W - P - 84, y, 84, 36)
        y += 36 + 10

        # Rename row
        self._rename_input_rect = pygame.Rect(bx + P, y, self.W - P*2 - 90, 36)
        self._rename_btn_rect   = pygame.Rect(bx + self.W - P - 84, y, 84, 36)
        y += 36 + 16

        # "Show initial message on load" checkbox
        self._hints_check_r = pygame.Rect(bx + P, y + 2, 22, 22)
        self._hints_row_r   = pygame.Rect(bx + P, y, self.W - P*2, 26)
        y += 26 + 14

        # Switch button
        self._switch_rect = pygame.Rect(bx + self.W // 2 - 90, y, 180, 32)

    def handle_event(self, ev):
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            pos = ev.pos
            if self._close_r.collidepoint(pos):
                self.result = {'action': 'close'}
                return self.result
            for i, r in enumerate(self._item_rects):
                if r.collidepoint(pos):
                    self.selected   = self.campaigns[i]
                    self.rename_buf = self.campaigns[i]   # pre-fill rename
                    self._typing = self._rtyping = False
                    return None
            for i, r in enumerate(self._del_rects):
                if r.collidepoint(pos):
                    name = self.campaigns[i]
                    if name != 'default' and name != self.active:
                        self.result = {'action': 'delete', 'name': name}
                        return self.result
                    return None
            if self._hints_row_r.collidepoint(pos):
                new_val = not self.hints_map.get(self.selected, True)
                self.hints_map[self.selected] = new_val
                self.result = {'action': 'toggle_hints',
                               'campaign': self.selected, 'enabled': new_val}
                return self.result
            if self._switch_rect.collidepoint(pos):
                if self.selected and self.selected != self.active:
                    self.result = {'action': 'switch', 'name': self.selected}
                    return self.result
                return None
            if self._create_rect.collidepoint(pos):
                n = self.name_buf.strip()
                if n:
                    self.result = {'action': 'create', 'name': n}
                    return self.result
                return None
            if self._rename_btn_rect.collidepoint(pos):
                n = self.rename_buf.strip()
                if n and self.selected and n != self.selected:
                    self.result = {'action': 'rename', 'old': self.selected, 'new': n}
                    return self.result
                return None
            if self._input_rect.collidepoint(pos):
                self._typing = True; self._rtyping = False
            elif self._rename_input_rect.collidepoint(pos):
                self._rtyping = True; self._typing = False
            else:
                self._typing = self._rtyping = False

        elif ev.type == pygame.KEYDOWN:
            if self._typing:
                if ev.key == pygame.K_RETURN:
                    n = self.name_buf.strip()
                    if n:
                        self.result = {'action': 'create', 'name': n}
                        return self.result
                elif ev.key == pygame.K_BACKSPACE:
                    self.name_buf = self.name_buf[:-1]
                elif ev.key == pygame.K_ESCAPE:
                    self._typing = False
                elif ev.unicode and len(self.name_buf) < 40:
                    ch = ev.unicode
                    if ch.isalnum() or ch in ' _-':
                        self.name_buf += ch
            elif self._rtyping:
                if ev.key == pygame.K_RETURN:
                    n = self.rename_buf.strip()
                    if n and self.selected and n != self.selected:
                        self.result = {'action': 'rename', 'old': self.selected, 'new': n}
                        return self.result
                elif ev.key == pygame.K_BACKSPACE:
                    self.rename_buf = self.rename_buf[:-1]
                elif ev.key == pygame.K_ESCAPE:
                    self._rtyping = False
                elif ev.unicode and len(self.rename_buf) < 40:
                    ch = ev.unicode
                    if ch.isalnum() or ch in ' _-':
                        self.rename_buf += ch
            elif ev.key == pygame.K_ESCAPE:
                self.result = {'action': 'close'}
                return self.result

        return None

    def draw(self, surface):
        dim = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 160))
        surface.blit(dim, (0, 0))

        bx, by = self.bx, self.by
        P = self.PAD

        box = pygame.Rect(bx, by, self.W, self.H)
        pygame.draw.rect(surface, (28, 28, 40), box, border_radius=10)
        pygame.draw.rect(surface, (90, 70, 140), box, 2, border_radius=10)

        title = self.font.render('Campaigns', True, (210, 190, 255))
        surface.blit(title, (bx + P, by + 12))

        pygame.draw.rect(surface, (120, 40, 40), self._close_r, border_radius=4)
        xl = self.font.render('X', True, WHITE)
        surface.blit(xl, (self._close_r.centerx - xl.get_width() // 2,
                          self._close_r.centery - xl.get_height() // 2))

        # Campaign list
        for i, name in enumerate(self.campaigns):
            r  = self._item_rects[i]
            dr = self._del_rects[i]
            is_active   = name == self.active
            is_selected = name == self.selected
            bg = (55, 120, 55) if is_active else ((55, 55, 110) if is_selected else (42, 42, 60))
            pygame.draw.rect(surface, bg, r, border_radius=5)
            pygame.draw.rect(surface, (90, 70, 140), r, 1, border_radius=5)
            tag = '  [active]' if is_active else ''
            lbl = self.font.render(name + tag, True, WHITE)
            surface.blit(lbl, (r.x + 10, r.centery - lbl.get_height() // 2))
            if name != 'default' and not is_active:
                pygame.draw.rect(surface, (130, 40, 40), dr, border_radius=4)
                dl = self.font.render('Del', True, WHITE)
                surface.blit(dl, (dr.centerx - dl.get_width() // 2,
                                  dr.centery - dl.get_height() // 2))

        # Create row
        ic = (100, 190, 100) if self._typing else (80, 80, 120)
        pygame.draw.rect(surface, (44, 46, 62), self._input_rect, border_radius=5)
        pygame.draw.rect(surface, ic, self._input_rect, 2, border_radius=5)
        disp = self.name_buf or 'New campaign name…'
        tc   = WHITE if self.name_buf else (100, 100, 130)
        tl   = self.font.render(disp, True, tc)
        surface.blit(tl, (self._input_rect.x + 8,
                          self._input_rect.centery - tl.get_height() // 2))
        cc = (50, 130, 50) if self.name_buf.strip() else (50, 70, 50)
        pygame.draw.rect(surface, cc, self._create_rect, border_radius=5)
        cl = self.font.render('Create', True, WHITE)
        surface.blit(cl, (self._create_rect.centerx - cl.get_width() // 2,
                          self._create_rect.centery - cl.get_height() // 2))

        # Rename row
        rc = (190, 160, 60) if self._rtyping else (80, 80, 120)
        pygame.draw.rect(surface, (44, 46, 62), self._rename_input_rect, border_radius=5)
        pygame.draw.rect(surface, rc, self._rename_input_rect, 2, border_radius=5)
        rdisp = self.rename_buf or 'Select a campaign to rename…'
        rtc   = WHITE if self.rename_buf else (100, 100, 130)
        rtl   = self.font.render(rdisp, True, rtc)
        surface.blit(rtl, (self._rename_input_rect.x + 8,
                           self._rename_input_rect.centery - rtl.get_height() // 2))
        can_rename = bool(self.rename_buf.strip() and self.selected
                          and self.rename_buf.strip() != self.selected)
        rbc = (160, 130, 40) if can_rename else (70, 65, 40)
        pygame.draw.rect(surface, rbc, self._rename_btn_rect, border_radius=5)
        rbl = self.font.render('Rename', True, WHITE)
        surface.blit(rbl, (self._rename_btn_rect.centerx - rbl.get_width() // 2,
                           self._rename_btn_rect.centery - rbl.get_height() // 2))

        # "Show initial message on load" checkbox
        cb = self._hints_check_r
        cb_bg = (GREEN if self.hints_enabled else TOOLBAR_BTN)
        pygame.draw.rect(surface, cb_bg, cb, border_radius=3)
        if self.hints_enabled:
            pygame.draw.line(surface, BLACK, (cb.x + 3, cb.centery),     (cb.x + 8,  cb.bottom - 4), 3)
            pygame.draw.line(surface, BLACK, (cb.x + 8, cb.bottom - 4),  (cb.right - 3, cb.y + 4),   3)
        else:
            pygame.draw.rect(surface, (80, 80, 100), cb, 1, border_radius=3)
        lbl = self.font.render('Show initial message on load', True, LIGHT_GRAY)
        surface.blit(lbl, (cb.right + 10, cb.centery - lbl.get_height() // 2))

        # Switch button
        can_switch = self.selected and self.selected != self.active
        sc = (60, 90, 170) if can_switch else (50, 55, 80)
        pygame.draw.rect(surface, sc, self._switch_rect, border_radius=5)
        sl = self.font.render('Switch to Selected', True, WHITE)
        surface.blit(sl, (self._switch_rect.centerx - sl.get_width() // 2,
                          self._switch_rect.centery - sl.get_height() // 2))


# ── Hidden-item placement dialog ───────────────────────────────────────────────

class HiddenItemDialog:
    """DM dialog to configure a hidden item before placing it on the map."""

    W, H = 420, 260
    _TITLE = 'Place Hidden Item'

    def __init__(self, font, screen_w, screen_h, existing=None):
        self.font   = font
        self.result = None           # None → still open; dict → committed
        self.done   = False
        bx = screen_w // 2 - self.W // 2
        by = screen_h // 2 - self.H // 2
        P  = 14

        # Pre-fill from existing item when editing
        self._dc_buf   = str(existing['dc'])          if existing else '15'
        self._rad_buf  = str(int(existing['radius'])) if existing else '50'
        self._desc_buf = existing['description']      if existing else ''
        self._focus    = 'desc'   # which field has keyboard focus

        self._box   = pygame.Rect(bx, by, self.W, self.H)
        self._close = pygame.Rect(bx + self.W - 28, by + 6, 22, 22)
        row1y = by + 48
        row2y = row1y + 52
        row3y = row2y + 52
        self._dc_rect   = pygame.Rect(bx + P + 110, row1y, 80,  32)
        self._rad_rect  = pygame.Rect(bx + P + 110, row2y, 80,  32)
        self._desc_rect = pygame.Rect(bx + P,        row3y, self.W - P*2, 36)
        bw = 90
        self._ok_rect   = pygame.Rect(bx + self.W // 2 - bw - 6, by + self.H - P - 32, bw, 32)
        self._can_rect  = pygame.Rect(bx + self.W // 2 + 6,       by + self.H - P - 32, bw, 32)

    # ── input helpers ─────────────────────────────────────────────────────────

    def _type(self, buf, ch, digits_only=False):
        if digits_only and not ch.isdigit():
            return buf
        return (buf + ch)[:64]

    def _back(self, buf):
        return buf[:-1]

    # ── event handling ────────────────────────────────────────────────────────

    def handle_event(self, ev):
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            p = ev.pos
            if self._close.collidepoint(p) or self._can_rect.collidepoint(p):
                self.done = True; return
            if self._ok_rect.collidepoint(p):
                self._commit(); return
            if self._dc_rect.collidepoint(p):   self._focus = 'dc'
            elif self._rad_rect.collidepoint(p): self._focus = 'rad'
            elif self._desc_rect.collidepoint(p): self._focus = 'desc'

        elif ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_ESCAPE:
                self.done = True; return
            if ev.key == pygame.K_RETURN:
                self._commit(); return
            if ev.key == pygame.K_TAB:
                order = ['dc', 'rad', 'desc']
                idx = order.index(self._focus)
                self._focus = order[(idx + 1) % len(order)]
                return
            if ev.key == pygame.K_BACKSPACE:
                if self._focus == 'dc':   self._dc_buf   = self._back(self._dc_buf)
                elif self._focus == 'rad': self._rad_buf  = self._back(self._rad_buf)
                else:                      self._desc_buf = self._back(self._desc_buf)
            else:
                ch = ev.unicode
                if self._focus == 'dc':    self._dc_buf   = self._type(self._dc_buf,  ch, True)
                elif self._focus == 'rad': self._rad_buf  = self._type(self._rad_buf, ch, True)
                else:                      self._desc_buf = self._type(self._desc_buf, ch)

    def _commit(self):
        dc  = int(self._dc_buf)  if self._dc_buf.isdigit()  else 15
        rad = int(self._rad_buf) if self._rad_buf.isdigit() else 50
        dc  = max(1, min(30, dc))
        rad = max(10, min(500, rad))
        self.result = {'dc': dc, 'radius': rad, 'description': self._desc_buf.strip()}
        self.done   = True

    # ── drawing ───────────────────────────────────────────────────────────────

    def draw(self, surface):
        pygame.draw.rect(surface, (30, 30, 50),  self._box, border_radius=8)
        pygame.draw.rect(surface, (100, 60, 180), self._box, 2, border_radius=8)

        title = self.font.render(self._TITLE, True, (220, 180, 255))
        surface.blit(title, (self._box.centerx - title.get_width() // 2,
                              self._box.y + 10))
        pygame.draw.rect(surface, (180, 60, 60), self._close, border_radius=4)
        xl = self.font.render('X', True, WHITE)
        surface.blit(xl, (self._close.centerx - xl.get_width() // 2,
                           self._close.centery - xl.get_height() // 2))

        def _row(label, rect, buf, field):
            lbl = self.font.render(label, True, (180, 180, 200))
            surface.blit(lbl, (rect.x - 106, rect.centery - lbl.get_height() // 2))
            col = (60, 100, 180) if self._focus == field else (45, 45, 65)
            pygame.draw.rect(surface, col, rect, border_radius=4)
            pygame.draw.rect(surface, (120, 120, 160), rect, 1, border_radius=4)
            txt = self.font.render(buf + ('|' if self._focus == field else ''), True, WHITE)
            surface.blit(txt, (rect.x + 6, rect.centery - txt.get_height() // 2))

        _row('DC (1-30):',      self._dc_rect,   self._dc_buf,   'dc')
        _row('Radius (px):',    self._rad_rect,  self._rad_buf,  'rad')
        _row('Description:', self._desc_rect, self._desc_buf, 'desc')

        for rect, label, col in [
            (self._ok_rect,  'Place',  (55, 130, 55)),
            (self._can_rect, 'Cancel', (100, 45, 45)),
        ]:
            pygame.draw.rect(surface, col, rect, border_radius=5)
            l = self.font.render(label, True, WHITE)
            surface.blit(l, (rect.centerx - l.get_width() // 2,
                              rect.centery - l.get_height() // 2))


# ── Trap placement dialog ──────────────────────────────────────────────────────

class TrapDialog:
    """DM dialog to configure a trap before placing it on the map."""

    W, H = 420, 210
    _TITLE = 'Place Trap'

    def __init__(self, font, screen_w, screen_h, existing=None):
        self.font   = font
        self.result = None
        self.done   = False
        bx = screen_w // 2 - self.W // 2
        by = screen_h // 2 - self.H // 2
        P  = 14

        self._rad_buf  = str(int(existing['radius'])) if existing else '50'
        self._desc_buf = existing['description']      if existing else ''
        self._focus    = 'desc'

        self._box   = pygame.Rect(bx, by, self.W, self.H)
        self._close = pygame.Rect(bx + self.W - 28, by + 6, 22, 22)
        row1y = by + 48
        row2y = row1y + 52
        self._rad_rect  = pygame.Rect(bx + P + 110, row1y, 80,  32)
        self._desc_rect = pygame.Rect(bx + P,        row2y, self.W - P*2, 36)
        bw = 90
        self._ok_rect  = pygame.Rect(bx + self.W // 2 - bw - 6, by + self.H - P - 32, bw, 32)
        self._can_rect = pygame.Rect(bx + self.W // 2 + 6,       by + self.H - P - 32, bw, 32)

    def handle_event(self, ev):
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            p = ev.pos
            if self._close.collidepoint(p) or self._can_rect.collidepoint(p):
                self.done = True; return
            if self._ok_rect.collidepoint(p):
                self._commit(); return
            if self._rad_rect.collidepoint(p):   self._focus = 'rad'
            elif self._desc_rect.collidepoint(p): self._focus = 'desc'
        elif ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_ESCAPE:
                self.done = True; return
            if ev.key == pygame.K_RETURN:
                self._commit(); return
            if ev.key == pygame.K_TAB:
                self._focus = 'desc' if self._focus == 'rad' else 'rad'; return
            if ev.key == pygame.K_BACKSPACE:
                if self._focus == 'rad': self._rad_buf  = self._rad_buf[:-1]
                else:                    self._desc_buf = self._desc_buf[:-1]
            else:
                ch = ev.unicode
                if self._focus == 'rad':
                    if ch.isdigit(): self._rad_buf = (self._rad_buf + ch)[:5]
                else:
                    self._desc_buf = (self._desc_buf + ch)[:128]

    def _commit(self):
        rad = int(self._rad_buf) if self._rad_buf.isdigit() else 50
        rad = max(10, min(500, rad))
        self.result = {'radius': rad, 'description': self._desc_buf.strip()}
        self.done   = True

    def draw(self, surface):
        pygame.draw.rect(surface, (40, 20, 20),   self._box, border_radius=8)
        pygame.draw.rect(surface, (200, 60, 60),  self._box, 2, border_radius=8)

        title = self.font.render(self._TITLE, True, (255, 140, 140))
        surface.blit(title, (self._box.centerx - title.get_width() // 2,
                              self._box.y + 10))
        pygame.draw.rect(surface, (180, 60, 60), self._close, border_radius=4)
        xl = self.font.render('X', True, WHITE)
        surface.blit(xl, (self._close.centerx - xl.get_width() // 2,
                           self._close.centery - xl.get_height() // 2))

        def _row(label, rect, buf, field):
            lbl = self.font.render(label, True, (180, 180, 200))
            surface.blit(lbl, (rect.x - 106, rect.centery - lbl.get_height() // 2))
            col = (140, 50, 50) if self._focus == field else (60, 30, 30)
            pygame.draw.rect(surface, col, rect, border_radius=4)
            pygame.draw.rect(surface, (180, 80, 80), rect, 1, border_radius=4)
            txt = self.font.render(buf + ('|' if self._focus == field else ''), True, WHITE)
            surface.blit(txt, (rect.x + 6, rect.centery - txt.get_height() // 2))

        _row('Radius (px):',  self._rad_rect,  self._rad_buf,  'rad')
        _row('Description:', self._desc_rect, self._desc_buf, 'desc')

        for rect, label, col in [
            (self._ok_rect,  'Place',  (55, 130, 55)),
            (self._can_rect, 'Cancel', (100, 45, 45)),
        ]:
            pygame.draw.rect(surface, col, rect, border_radius=5)
            l = self.font.render(label, True, WHITE)
            surface.blit(l, (rect.centerx - l.get_width() // 2,
                              rect.centery - l.get_height() // 2))


# ── DC roll popup ──────────────────────────────────────────────────────────────

class DCRollPopup:
    """Shown when a character is near a hidden item; DM enters the player's d20 roll."""

    W, H = 380, 200

    def __init__(self, font, screen_w, screen_h, item):
        self.font   = font
        self.item   = item        # HiddenItem object
        self.result = None        # None=open, True=found, False=not found
        self.done   = False
        self._buf   = ''
        bx = screen_w // 2 - self.W // 2
        by = screen_h // 2 - self.H // 2
        P  = 14
        self._box      = pygame.Rect(bx, by, self.W, self.H)
        self._input    = pygame.Rect(bx + self.W // 2 - 40, by + 108, 80, 34)
        self._ok_rect  = pygame.Rect(bx + self.W // 2 - 46, by + self.H - P - 32, 92, 32)

    def handle_event(self, ev):
        if ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_ESCAPE:
                self.done = True; return
            if ev.key == pygame.K_RETURN:
                self._commit(); return
            if ev.key == pygame.K_BACKSPACE:
                self._buf = self._buf[:-1]
            elif ev.unicode.isdigit():
                self._buf = (self._buf + ev.unicode)[:2]
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            if self._ok_rect.collidepoint(ev.pos):
                self._commit()

    def _commit(self):
        if not self._buf.isdigit():
            return
        roll = int(self._buf)
        self.result = roll >= self.item.dc
        self.done   = True

    def draw(self, surface):
        pygame.draw.rect(surface, (25, 30, 50), self._box, border_radius=8)
        pygame.draw.rect(surface, (100, 180, 255), self._box, 2, border_radius=8)

        lines = [
            ('A character notices something nearby!', (180, 220, 255)),
            ('Roll 1d20', (220, 220, 100)),
        ]
        y = self._box.y + 14
        for text, col in lines:
            lbl = self.font.render(text, True, col)
            surface.blit(lbl, (self._box.centerx - lbl.get_width() // 2, y))
            y += lbl.get_height() + 6

        # Roll input
        pygame.draw.rect(surface, (50, 60, 90), self._input, border_radius=4)
        pygame.draw.rect(surface, (100, 180, 255), self._input, 1, border_radius=4)
        val = self.font.render(self._buf + '|', True, WHITE)
        surface.blit(val, (self._input.centerx - val.get_width() // 2,
                            self._input.centery - val.get_height() // 2))

        pygame.draw.rect(surface, (55, 120, 55), self._ok_rect, border_radius=5)
        ok = self.font.render('Roll!', True, WHITE)
        surface.blit(ok, (self._ok_rect.centerx - ok.get_width() // 2,
                           self._ok_rect.centery - ok.get_height() // 2))


# ── DC roll result popup ───────────────────────────────────────────────────────

class DCResultPopup:
    """Shows the outcome of a DC roll (found / not found)."""

    W, H = 400, 160

    def __init__(self, font, screen_w, screen_h, found, description):
        self.font   = font
        self.done   = False
        bx = screen_w // 2 - self.W // 2
        by = screen_h // 2 - self.H // 2
        self._box    = pygame.Rect(bx, by, self.W, self.H)
        self._ok     = pygame.Rect(bx + self.W // 2 - 46, by + self.H - 46, 92, 32)
        if found:
            self._title = 'You found something!'
            self._body  = description if description else 'A hidden object.'
            self._tcol  = (120, 255, 120)
        else:
            self._title = 'You notice nothing of importance.'
            self._body  = ''
            self._tcol  = (180, 180, 180)

    def handle_event(self, ev):
        if ev.type == pygame.KEYDOWN and ev.key in (pygame.K_RETURN, pygame.K_ESCAPE):
            self.done = True
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            if self._ok.collidepoint(ev.pos):
                self.done = True

    def draw(self, surface):
        pygame.draw.rect(surface, (25, 35, 25), self._box, border_radius=8)
        pygame.draw.rect(surface, (80, 200, 80), self._box, 2, border_radius=8)
        title = self.font.render(self._title, True, self._tcol)
        surface.blit(title, (self._box.centerx - title.get_width() // 2,
                              self._box.y + 18))
        if self._body:
            body = self.font.render(self._body, True, (220, 220, 180))
            surface.blit(body, (self._box.centerx - body.get_width() // 2,
                                self._box.y + 52))
        pygame.draw.rect(surface, (55, 120, 55), self._ok, border_radius=5)
        ok = self.font.render('OK', True, WHITE)
        surface.blit(ok, (self._ok.centerx - ok.get_width() // 2,
                           self._ok.centery - ok.get_height() // 2))


# ── NewSceneChoicePopup ───────────────────────────────────────────────────────

class NewSceneChoicePopup:
    """Ask whether to create a blank scene or generate a dungeon map."""
    W, H = 420, 162

    def __init__(self, font, screen_w, screen_h):
        self.font = font
        bx = (screen_w - self.W) // 2
        by = (screen_h - self.H) // 2
        self._box     = pygame.Rect(bx, by, self.W, self.H)
        self._blank_r = pygame.Rect(bx + 20,            by + 104, 172, 38)
        self._gen_r   = pygame.Rect(bx + self.W - 192,  by + 104, 172, 38)

    def draw(self, surface):
        pygame.draw.rect(surface, PANEL_BG,     self._box, border_radius=8)
        pygame.draw.rect(surface, PANEL_BORDER, self._box, 2, border_radius=8)
        title = self.font.render('Create New Scene', True, WHITE)
        surface.blit(title, (self._box.centerx - title.get_width() // 2,
                             self._box.y + 18))
        sub = self.font.render('Choose map type for this scene:', True, LIGHT_GRAY)
        surface.blit(sub, (self._box.centerx - sub.get_width() // 2,
                           self._box.y + 56))
        pygame.draw.rect(surface, TOOLBAR_BTN,   self._blank_r, border_radius=5)
        bt = self.font.render('Blank Map', True, WHITE)
        surface.blit(bt, (self._blank_r.centerx - bt.get_width()  // 2,
                          self._blank_r.centery - bt.get_height() // 2))
        pygame.draw.rect(surface, (40, 100, 60), self._gen_r, border_radius=5)
        gt = self.font.render('Generate Map', True, WHITE)
        surface.blit(gt, (self._gen_r.centerx - gt.get_width()  // 2,
                          self._gen_r.centery - gt.get_height() // 2))

    def hit(self, pos):
        """Returns 'blank', 'generate', or 'cancel'."""
        if self._blank_r.collidepoint(pos):
            return 'blank'
        if self._gen_r.collidepoint(pos):
            return 'generate'
        if not self._box.collidepoint(pos):
            return 'cancel'
        return None

    def key(self, event):
        if event.key == pygame.K_ESCAPE:
            return 'cancel'
        return None


# ── DungeonGenDialog ──────────────────────────────────────────────────────────

class DungeonGenDialog:
    """Split-panel dialog: params on the left, live preview on the right."""

    # W is computed from screen_w in __init__; H is fixed
    H = 510

    _SIZES      = ['TINY', 'SMALL', 'MEDIUM', 'LARGE', 'XLARGE']
    _ARCHETYPES = ['CLASSIC', 'WARREN', 'TEMPLE', 'CRYPT', 'CAVERN', 'FORTRESS', 'LAIR']
    _SYMMETRIES = ['NONE', 'BILATERAL', 'RADIAL_2', 'RADIAL_4', 'PARTIAL']

    # (attr, short label, min, max, default)
    _LEFT_SLIDERS = [
        ('density',           'Density',      0.0, 1.0,  0.50),
        ('room_size_bias',    'Room Size',   -1.0, 1.0,  0.00),
        ('round_room_chance', 'Round Rooms',  0.0, 1.0,  0.15),
        ('hall_chance',       'Hall Chance',  0.0, 1.0,  0.10),
        ('linearity',         'Linearity',    0.0, 1.0,  0.30),
        ('loop_factor',       'Loop Factor',  0.0, 1.0,  0.30),
    ]
    _RIGHT_SLIDERS = [
        ('winding',                  'Winding',      0.0, 1.0,  0.00),
        ('extra_room_connections',   'Extra Conn.',  0.0, 1.0,  0.20),
        ('extra_passage_junctions',  'Junctions',    0.0, 1.0,  0.15),
        ('stair_frequency',          'Stairs',       0.0, 1.0,  0.10),
        ('symmetry_break',           'Sym. Break',   0.0, 1.0,  0.20),
        ('water_threshold',          'Water Level', -1.0, 1.0,  0.15),
    ]
    _TRACK_W  = 148
    _LABEL_W  = 108
    _VAL_W    = 42
    _ROW_H    = 28

    def __init__(self, font, screen_w, screen_h, default_name='', initial_params=None):
        self.font   = font
        self._small = pygame.font.Font(None, 17)

        # Size adapts to screen; right panel is 320px, divider 1px, gap each side
        RIGHTY  = 320          # right-panel content width
        DIVX    = 16           # gap between panels
        LEFT_W  = min(560, screen_w - RIGHTY - DIVX - 40)
        W       = LEFT_W + DIVX + RIGHTY + 32   # 16px outer padding each side
        H       = self.H
        self.W  = W
        bx = max(0, (screen_w - W) // 2)
        by = max(0, (screen_h - H) // 2)
        self._bx, self._by = bx, by
        self._box = pygame.Rect(bx, by, W, H)
        P = 16

        # --- mutable state (defaults) ---
        self.name          = default_name
        self.size_idx      = 2   # MEDIUM
        self.arch_idx      = 0   # CLASSIC
        self.sym_idx       = 0   # NONE
        self.water_enabled = False
        self._pw_buf       = '1'
        self._lv_buf       = '1'
        self._sd_buf       = ''
        self._active       = None
        self._dragging     = None
        self._vals         = {a: d for a, _, mn, mx, d
                              in self._LEFT_SLIDERS + self._RIGHT_SLIDERS}
        self.done   = False
        self.result = None   # None = cancelled; dict = accepted params

        # Generation state for the preview panel
        # 'idle' | 'generating' | 'preview' | 'error'
        self._gen_state    = 'idle'
        self._preview_surf = None   # scaled thumbnail pygame.Surface
        self._preview_tick = 0      # animation counter for spinner
        self._error_msg    = ''

        # Apply previous params when reopened from regenerate
        if initial_params:
            p = initial_params
            self.name = p.get('scene_name', default_name) or default_name
            s = p.get('size', 'MEDIUM')
            if s in self._SIZES:       self.size_idx  = self._SIZES.index(s)
            a = p.get('archetype', 'CLASSIC')
            if a in self._ARCHETYPES:  self.arch_idx  = self._ARCHETYPES.index(a)
            sy = p.get('symmetry', 'NONE')
            if sy in self._SYMMETRIES: self.sym_idx   = self._SYMMETRIES.index(sy)
            self.water_enabled = p.get('water_enabled', False)
            self._pw_buf = str(p.get('passage_width', 1))
            self._lv_buf = str(p.get('levels', 1))
            seed = p.get('seed')
            self._sd_buf = str(seed) if seed is not None else ''
            for attr, *_ in self._LEFT_SLIDERS + self._RIGHT_SLIDERS:
                if attr in p:
                    self._vals[attr] = p[attr]

        # ── LEFT PANEL layout (fills full height) ────────────────────────────
        lx0 = bx + P          # left panel inner left edge
        lx1 = bx + P + LEFT_W # left panel inner right edge (= divider)

        # Fixed block heights (px) — title, name, dd1, dd2, param-header, inputs
        BT, BN, BD1, BD2, BH, BI = 44, 42, 42, 42, 22, 44
        n_slider_rows = len(self._LEFT_SLIDERS)   # 6
        dyn_row_h = max(28, (H - 2*P - BT - BN - BD1 - BD2 - BH - BI) // n_slider_rows)
        self._dyn_row_h = dyn_row_h

        y = by + P

        # Title
        self._title_y = y + (BT - 20) // 2   # vertically centred in block
        y += BT

        # Scene name
        mid_n = y + (BN - 28) // 2
        self._name_lp   = (lx0, mid_n + 4)
        self._name_rect = pygame.Rect(lx0 + 54, mid_n, LEFT_W - 54, 28)
        y += BN

        # Dropdowns row 1: Size | Archetype
        mid_d1 = y + (BD1 - 26) // 2
        self._size_lp  = (lx0, mid_d1 + 4)
        self._size_btn = pygame.Rect(lx0 + 40, mid_d1, 92, 26)
        self._arch_lp  = (lx0 + 148, mid_d1 + 4)
        self._arch_btn = pygame.Rect(lx0 + 188, mid_d1, min(130, LEFT_W - 192), 26)
        y += BD1

        # Dropdowns row 2: Symmetry | Water checkbox
        mid_d2 = y + (BD2 - 26) // 2
        self._sym_lp    = (lx0, mid_d2 + 4)
        self._sym_btn   = pygame.Rect(lx0 + 70, mid_d2, 130, 26)
        self._water_chk = pygame.Rect(lx0 + 220, mid_d2 + 3, 20, 20)
        self._water_lp  = (lx0 + 246, mid_d2 + 4)
        y += BD2

        # Slider section header sits inside a BH-px block
        self._slider_hdr_y = y + (BH - 14) // 2
        y += BH

        # Sliders in two columns
        col_w  = (LEFT_W - 8) // 2
        slx    = lx0
        srx    = lx0 + col_w + 8
        LBL_W  = max(70, col_w - 145)
        TRK_W  = col_w - LBL_W - 42
        self._slider_y0 = y
        self._lx, self._rx = slx, srx
        self._LABEL_W = LBL_W
        self._TRACK_W = TRK_W
        self._slider_rects: dict = {}
        for i, (attr, *_) in enumerate(self._LEFT_SLIDERS):
            ty   = y + i * dyn_row_h
            mid  = ty + (dyn_row_h - 8) // 2
            self._slider_rects[attr] = pygame.Rect(slx + LBL_W + 4, mid, TRK_W, 8)
        for i, (attr, *_) in enumerate(self._RIGHT_SLIDERS):
            ty   = y + i * dyn_row_h
            mid  = ty + (dyn_row_h - 8) // 2
            self._slider_rects[attr] = pygame.Rect(srx + LBL_W + 4, mid, TRK_W, 8)
        y += n_slider_rows * dyn_row_h

        # Bottom integer inputs
        mid_i = y + (BI - 26) // 2
        self._pw_lp   = (lx0, mid_i + 4)
        self._pw_rect = pygame.Rect(lx0 + 107, mid_i, 42, 26)
        self._lv_lp   = (lx0 + 160, mid_i + 4)
        self._lv_rect = pygame.Rect(lx0 + 212, mid_i, 42, 26)
        self._sd_lp   = (lx0 + 264, mid_i + 4)
        self._sd_rect = pygame.Rect(lx0 + 300, mid_i, LEFT_W - 304, 26)

        self._inputs = {
            'name': self._name_rect,
            'pw':   self._pw_rect,
            'lv':   self._lv_rect,
            'sd':   self._sd_rect,
        }

        # ── RIGHT PANEL layout ───────────────────────────────────────────────
        self._divider_x = lx1 + DIVX // 2
        rx0 = lx1 + DIVX
        rx1 = bx + W - P

        self._preview_lp  = (rx0, by + P + 4)

        BTN_H  = 36
        BTN_GAP = 6
        btns_h = 3 * BTN_H + 2 * BTN_GAP
        img_y  = by + P + 22
        img_h  = H - 2 * P - 22 - 10 - btns_h
        img_w  = rx1 - rx0
        self._preview_box = pygame.Rect(rx0, img_y, img_w, img_h)

        btn_y = img_y + img_h + 10
        self._accept_btn = pygame.Rect(rx0, btn_y, img_w, BTN_H)
        btn_y += BTN_H + BTN_GAP
        self._gen_btn    = pygame.Rect(rx0, btn_y, img_w, BTN_H)
        btn_y += BTN_H + BTN_GAP
        self._cancel_btn = pygame.Rect(rx0, btn_y, img_w, BTN_H)

    # ── state control (called by main.py) ────────────────────────────────────

    def set_generating(self):
        self._gen_state    = 'generating'
        self._preview_surf = None
        self._preview_tick = 0
        self._error_msg    = ''

    def set_preview(self, image_path: str):
        """Load thumbnail from the generated PNG and switch to preview state."""
        try:
            raw  = pygame.image.load(image_path).convert()
            rw, rh = raw.get_size()
            tw, th = self._preview_box.width, self._preview_box.height
            scale = min(tw / rw, th / rh)
            nw, nh = int(rw * scale), int(rh * scale)
            self._preview_surf = pygame.transform.smoothscale(raw, (nw, nh))
        except Exception:
            self._preview_surf = None
        self._gen_state = 'preview'

    def set_error(self, msg: str):
        self._error_msg = msg
        self._gen_state = 'error'

    def tick(self):
        """Called every frame to animate the spinner."""
        if self._gen_state == 'generating':
            self._preview_tick += 1

    # ── internal helpers ──────────────────────────────────────────────────────

    def _buf(self, key):
        return {'name': self.name, 'pw': self._pw_buf,
                'lv': self._lv_buf, 'sd': self._sd_buf}[key]

    def _set_buf(self, key, val):
        if key == 'name': self.name     = val
        elif key == 'pw': self._pw_buf  = val
        elif key == 'lv': self._lv_buf  = val
        elif key == 'sd': self._sd_buf  = val

    def _knob_x(self, attr, mn, mx, rect):
        ratio = (self._vals[attr] - mn) / (mx - mn) if mx != mn else 0
        return int(rect.x + ratio * rect.width)

    def _draw_slider(self, surface, attr, label, mn, mx, rect, enabled=True):
        ly = rect.centery - self._small.get_height() // 2
        lbl = self._small.render(label, True, LIGHT_GRAY if enabled else GRAY)
        surface.blit(lbl, (rect.x - self._LABEL_W - 4, ly))
        track_col = (80, 80, 80) if enabled else (50, 50, 50)
        pygame.draw.rect(surface, track_col, rect, border_radius=4)
        if enabled:
            kx = self._knob_x(attr, mn, mx, rect)
            pygame.draw.circle(surface, (180, 180, 220), (kx, rect.centery), 6)
        vsurf = self._small.render(f'{self._vals[attr]:.2f}', True,
                                   LIGHT_GRAY if enabled else GRAY)
        surface.blit(vsurf, (rect.right + 4, ly))

    def _draw_dropdown(self, surface, rect, label, value):
        lsurf = self._small.render(label, True, LIGHT_GRAY)
        surface.blit(lsurf, (rect.x - self._small.size(label)[0] - 4, rect.y + 5))
        pygame.draw.rect(surface, TOOLBAR_BTN,   rect, border_radius=4)
        pygame.draw.rect(surface, PANEL_BORDER,  rect, 1, border_radius=4)
        vsurf = self._small.render(value, True, WHITE)
        surface.blit(vsurf, (rect.centerx - vsurf.get_width()  // 2,
                             rect.centery - vsurf.get_height() // 2))
        arrow = self._small.render('v', True, LIGHT_GRAY)
        surface.blit(arrow, (rect.right - arrow.get_width() - 4,
                             rect.centery - arrow.get_height() // 2))

    def _draw_input(self, surface, rect, buf, active):
        bg = (55, 55, 80) if active else TOOLBAR_BTN
        pygame.draw.rect(surface, bg, rect, border_radius=4)
        pygame.draw.rect(surface, PANEL_BORDER if not active else (120, 120, 200),
                         rect, 1, border_radius=4)
        txt = buf + ('|' if active else '')
        tsurf = self._small.render(txt, True, WHITE)
        surface.blit(tsurf, (rect.x + 4, rect.centery - tsurf.get_height() // 2))

    # ── draw ─────────────────────────────────────────────────────────────────

    def draw(self, surface):
        bx, by = self._bx, self._by
        pygame.draw.rect(surface, PANEL_BG,     self._box, border_radius=8)
        pygame.draw.rect(surface, PANEL_BORDER, self._box, 2, border_radius=8)

        # Vertical divider
        pygame.draw.line(surface, PANEL_BORDER,
                         (self._divider_x, by + 10),
                         (self._divider_x, by + self.H - 10))

        # ── Left panel ───────────────────────────────────────────────────────
        title = self.font.render('Generate Dungeon Map', True, WHITE)
        title_cx = (self._bx + self._divider_x) // 2
        surface.blit(title, (title_cx - title.get_width() // 2, self._title_y))

        # Scene name
        nl = self._small.render('Name:', True, LIGHT_GRAY)
        surface.blit(nl, self._name_lp)
        self._draw_input(surface, self._name_rect, self.name, self._active == 'name')

        # Dropdowns
        self._draw_dropdown(surface, self._size_btn,
                            'Size:', self._SIZES[self.size_idx])
        self._draw_dropdown(surface, self._arch_btn,
                            'Arch:', self._ARCHETYPES[self.arch_idx])
        self._draw_dropdown(surface, self._sym_btn,
                            'Symmetry:', self._SYMMETRIES[self.sym_idx])

        # Water checkbox
        wc = self._water_chk
        pygame.draw.rect(surface, TOOLBAR_BTN, wc, border_radius=3)
        pygame.draw.rect(surface, PANEL_BORDER, wc, 1, border_radius=3)
        if self.water_enabled:
            pygame.draw.line(surface, (100, 200, 100),
                             (wc.x + 2, wc.centery), (wc.x + 6, wc.bottom - 3), 2)
            pygame.draw.line(surface, (100, 200, 100),
                             (wc.x + 6, wc.bottom - 3), (wc.right - 2, wc.y + 3), 2)
        wl = self._small.render('Water Features', True, LIGHT_GRAY)
        surface.blit(wl, self._water_lp)

        # Slider header
        hdr = self._small.render('- Parameters -', True, GRAY)
        surface.blit(hdr, (self._lx, self._slider_hdr_y))

        for attr, label, mn, mx, _ in self._LEFT_SLIDERS:
            self._draw_slider(surface, attr, label, mn, mx,
                              self._slider_rects[attr])
        for attr, label, mn, mx, _ in self._RIGHT_SLIDERS:
            enabled = attr != 'water_threshold' or self.water_enabled
            self._draw_slider(surface, attr, label, mn, mx,
                              self._slider_rects[attr], enabled=enabled)

        # Bottom integer inputs
        pwl = self._small.render('Passage Width:', True, LIGHT_GRAY)
        surface.blit(pwl, self._pw_lp)
        self._draw_input(surface, self._pw_rect, self._pw_buf, self._active == 'pw')

        lvl = self._small.render('Levels:', True, LIGHT_GRAY)
        surface.blit(lvl, self._lv_lp)
        self._draw_input(surface, self._lv_rect, self._lv_buf, self._active == 'lv')

        sdl = self._small.render('Seed:', True, LIGHT_GRAY)
        surface.blit(sdl, self._sd_lp)
        self._draw_input(surface, self._sd_rect, self._sd_buf, self._active == 'sd')

        # ── Right panel ──────────────────────────────────────────────────────
        plbl = self._small.render('Preview', True, LIGHT_GRAY)
        surface.blit(plbl, self._preview_lp)

        # Preview box outline
        pygame.draw.rect(surface, (50, 50, 50), self._preview_box)
        pygame.draw.rect(surface, PANEL_BORDER, self._preview_box, 1)

        pb = self._preview_box
        if self._gen_state == 'idle':
            msg = self._small.render('Click Generate to preview', True, GRAY)
            surface.blit(msg, (pb.centerx - msg.get_width()  // 2,
                               pb.centery - msg.get_height() // 2))

        elif self._gen_state == 'generating':
            dots = '.' * (1 + (self._preview_tick // 20) % 4)
            msg  = self._small.render(f'Generating{dots}', True, LIGHT_GRAY)
            surface.blit(msg, (pb.centerx - msg.get_width()  // 2,
                               pb.centery - msg.get_height() // 2))

        elif self._gen_state == 'preview' and self._preview_surf:
            sx = pb.x + (pb.width  - self._preview_surf.get_width())  // 2
            sy = pb.y + (pb.height - self._preview_surf.get_height()) // 2
            surface.blit(self._preview_surf, (sx, sy))

        elif self._gen_state == 'error':
            msg = self._small.render('Error — see console', True, RED)
            surface.blit(msg, (pb.centerx - msg.get_width()  // 2,
                               pb.centery - msg.get_height() // 2))

        # Accept button (only active in preview state)
        if self._gen_state == 'preview':
            pygame.draw.rect(surface, (40, 120, 55), self._accept_btn, border_radius=5)
            at = self.font.render('Accept & Import', True, WHITE)
        else:
            pygame.draw.rect(surface, (40, 60, 40), self._accept_btn, border_radius=5)
            at = self.font.render('Accept & Import', True, GRAY)
        surface.blit(at, (self._accept_btn.centerx - at.get_width()  // 2,
                          self._accept_btn.centery - at.get_height() // 2))

        # Generate / Regenerate button
        busy = self._gen_state == 'generating'
        gen_col = (50, 50, 50) if busy else (40, 80, 150)
        pygame.draw.rect(surface, gen_col, self._gen_btn, border_radius=5)
        gen_lbl = 'Regenerate' if self._gen_state == 'preview' else 'Generate Preview'
        if busy: gen_lbl = 'Generating...'
        gs = self.font.render(gen_lbl, True, GRAY if busy else WHITE)
        surface.blit(gs, (self._gen_btn.centerx - gs.get_width()  // 2,
                          self._gen_btn.centery - gs.get_height() // 2))

        # Cancel button
        pygame.draw.rect(surface, TOOLBAR_BTN, self._cancel_btn, border_radius=5)
        cs = self.font.render('Cancel', True, WHITE)
        surface.blit(cs, (self._cancel_btn.centerx - cs.get_width()  // 2,
                          self._cancel_btn.centery - cs.get_height() // 2))

    # ── events ────────────────────────────────────────────────────────────────

    def _commit_input(self):
        if self._active in ('pw', 'lv'):
            buf = self._buf(self._active)
            try:
                v = max(1, int(buf))
            except ValueError:
                v = 1
            self._set_buf(self._active, str(v))

    def mouse_down(self, pos):
        # Text inputs
        for key, rect in self._inputs.items():
            if rect.collidepoint(pos):
                self._commit_input()
                self._active = key
                return None

        # Sliders (only left panel)
        for attr, _, mn, mx, _ in self._LEFT_SLIDERS + self._RIGHT_SLIDERS:
            tr = self._slider_rects[attr]
            if tr.inflate(0, 14).collidepoint(pos):
                if attr == 'water_threshold' and not self.water_enabled:
                    return None
                self._dragging = (attr, mn, mx, tr)
                self._update_drag(pos)
                return None

        # Dropdowns
        if self._size_btn.collidepoint(pos):
            self.size_idx = (self.size_idx + 1) % len(self._SIZES);  return None
        if self._arch_btn.collidepoint(pos):
            self.arch_idx = (self.arch_idx + 1) % len(self._ARCHETYPES); return None
        if self._sym_btn.collidepoint(pos):
            self.sym_idx  = (self.sym_idx  + 1) % len(self._SYMMETRIES); return None
        if self._water_chk.collidepoint(pos):
            self.water_enabled = not self.water_enabled; return None

        # Right-panel buttons
        if self._accept_btn.collidepoint(pos):
            if self._gen_state == 'preview':
                self.done = True
                self.result = self._collect_params()
            return None

        if self._gen_btn.collidepoint(pos):
            if self._gen_state != 'generating':
                return ('generate', self._collect_params())
            return None

        if self._cancel_btn.collidepoint(pos):
            self.done = True
            return None

        if not self._box.collidepoint(pos):
            self._commit_input()
            self._active = None
        return None

    def _update_drag(self, pos):
        attr, mn, mx, tr = self._dragging
        ratio = max(0.0, min(1.0, (pos[0] - tr.x) / tr.width))
        self._vals[attr] = round(mn + ratio * (mx - mn), 2)

    def mouse_motion(self, pos):
        if self._dragging:
            self._update_drag(pos)

    def mouse_up(self, pos):
        if self._dragging:
            self._update_drag(pos)
            self._dragging = None

    def key(self, event):
        if event.key == pygame.K_ESCAPE:
            self._commit_input()
            self._active = None
            self.done = True
            return None
        if event.key == pygame.K_RETURN:
            self._commit_input()
            if self._gen_state == 'preview' and self._active is None:
                self.done   = True
                self.result = self._collect_params()
                return None
            if self._active is None:
                return ('generate', self._collect_params())
            return None
        if event.key == pygame.K_TAB:
            self._commit_input()
            order = ['name', 'pw', 'lv', 'sd']
            self._active = order[(order.index(self._active) + 1) % len(order)] \
                           if self._active in order else 'name'
            return None
        if self._active is None:
            return None
        buf = self._buf(self._active)
        if event.key == pygame.K_BACKSPACE:
            self._set_buf(self._active, buf[:-1])
        elif event.unicode and event.unicode.isprintable():
            self._set_buf(self._active, buf + event.unicode)
        return None

    def _collect_params(self) -> dict:
        self._commit_input()
        try:   pw = max(1, int(self._pw_buf or '1'))
        except ValueError: pw = 1
        try:   lv = max(1, int(self._lv_buf or '1'))
        except ValueError: lv = 1
        seed = None
        if self._sd_buf.strip():
            try:   seed = int(self._sd_buf.strip()) % (2 ** 31)
            except ValueError: pass
        return {
            'scene_name':              self.name or 'Generated Dungeon',
            'size':                    self._SIZES[self.size_idx],
            'archetype':               self._ARCHETYPES[self.arch_idx],
            'symmetry':                self._SYMMETRIES[self.sym_idx],
            'water_enabled':           self.water_enabled,
            'passage_width':           pw,
            'levels':                  lv,
            'seed':                    seed,
            **{a: self._vals[a] for a, *_ in self._LEFT_SLIDERS + self._RIGHT_SLIDERS},
        }


# ── DungeonGenProgressPopup ───────────────────────────────────────────────────

class DungeonGenProgressPopup:
    """Modal overlay shown while dungeon generation runs in background."""
    W, H = 360, 100

    def __init__(self, font, screen_w, screen_h):
        self.font = font
        bx = (screen_w - self.W) // 2
        by = (screen_h - self.H) // 2
        self._box = pygame.Rect(bx, by, self.W, self.H)
        self._tick = 0

    def update(self):
        self._tick += 1

    def draw(self, surface):
        pygame.draw.rect(surface, PANEL_BG,     self._box, border_radius=8)
        pygame.draw.rect(surface, PANEL_BORDER, self._box, 2, border_radius=8)
        dots = '.' * (1 + (self._tick // 20) % 4)
        msg  = self.font.render(f'Generating dungeon{dots}', True, LIGHT_GRAY)
        surface.blit(msg, (self._box.centerx - msg.get_width()  // 2,
                           self._box.centery - msg.get_height() // 2))


# ── DungeonGenPreviewPopup ────────────────────────────────────────────────────

class DungeonGenPreviewPopup:
    """Shows a thumbnail of the generated dungeon with Accept / Regenerate / Cancel."""
    THUMB = 420
    P     = 14

    def __init__(self, font, screen_w, screen_h, image_path):
        self.font = font
        self.done   = False
        self.result = None   # 'accept' | 'regenerate' | 'cancel'

        W = self.THUMB + self.P * 2
        H = self.P + 26 + 8 + self.THUMB + 10 + 38 + self.P   # title+img+btns
        bx = (screen_w - W) // 2
        by = (screen_h - H) // 2
        self._box = pygame.Rect(bx, by, W, H)

        # Load thumbnail
        try:
            raw  = pygame.image.load(image_path).convert()
            rw, rh = raw.get_size()
            scale = min(self.THUMB / rw, self.THUMB / rh)
            nw, nh = int(rw * scale), int(rh * scale)
            self._thumb = pygame.transform.smoothscale(raw, (nw, nh))
        except Exception:
            self._thumb = pygame.Surface((self.THUMB, self.THUMB))
            self._thumb.fill((60, 60, 60))
            nw, nh = self.THUMB, self.THUMB

        thumb_x = bx + (W - nw) // 2
        thumb_y = by + self.P + 26 + 8
        self._thumb_rect = pygame.Rect(thumb_x, thumb_y, nw, nh)

        btn_y    = thumb_y + nh + 10
        btn_w    = (W - self.P * 2 - 16) // 3
        self._accept_btn = pygame.Rect(bx + self.P,                btn_y, btn_w, 34)
        self._regen_btn  = pygame.Rect(bx + self.P + btn_w + 8,   btn_y, btn_w, 34)
        self._cancel_btn = pygame.Rect(bx + self.P + (btn_w + 8) * 2, btn_y, btn_w, 34)

        self._title_pos  = (bx + W // 2, by + self.P + 6)

    def draw(self, surface):
        pygame.draw.rect(surface, PANEL_BG,     self._box, border_radius=8)
        pygame.draw.rect(surface, PANEL_BORDER, self._box, 2, border_radius=8)

        title = self.font.render('Generated Dungeon Preview', True, WHITE)
        surface.blit(title, (self._title_pos[0] - title.get_width() // 2,
                             self._title_pos[1]))

        # Thumbnail border + image
        pygame.draw.rect(surface, PANEL_BORDER,
                         self._thumb_rect.inflate(2, 2), 1)
        surface.blit(self._thumb, self._thumb_rect)

        # Accept (green)
        pygame.draw.rect(surface, (40, 120, 55), self._accept_btn, border_radius=5)
        at = self.font.render('Accept', True, WHITE)
        surface.blit(at, (self._accept_btn.centerx - at.get_width()  // 2,
                          self._accept_btn.centery - at.get_height() // 2))

        # Regenerate (blue-purple)
        pygame.draw.rect(surface, (60, 80, 160), self._regen_btn, border_radius=5)
        rt = self.font.render('Regenerate', True, WHITE)
        surface.blit(rt, (self._regen_btn.centerx - rt.get_width()  // 2,
                          self._regen_btn.centery - rt.get_height() // 2))

        # Cancel (dark)
        pygame.draw.rect(surface, TOOLBAR_BTN, self._cancel_btn, border_radius=5)
        ct = self.font.render('Cancel', True, WHITE)
        surface.blit(ct, (self._cancel_btn.centerx - ct.get_width()  // 2,
                          self._cancel_btn.centery - ct.get_height() // 2))

    def hit(self, pos):
        if self._accept_btn.collidepoint(pos):
            self.result = 'accept';     self.done = True
        elif self._regen_btn.collidepoint(pos):
            self.result = 'regenerate'; self.done = True
        elif self._cancel_btn.collidepoint(pos):
            self.result = 'cancel';     self.done = True
        elif not self._box.collidepoint(pos):
            self.result = 'cancel';     self.done = True

    def key(self, event):
        if event.key == pygame.K_RETURN:
            self.result = 'accept';     self.done = True
        elif event.key == pygame.K_ESCAPE:
            self.result = 'cancel';     self.done = True
