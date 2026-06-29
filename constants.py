# constants.py  –  shared colours, sizes, and condition definitions
BLACK      = (0,   0,   0)
WHITE      = (255, 255, 255)
RED        = (220,  50,  47)
GREEN      = (  0, 180,   0)
BLUE       = ( 38, 139, 210)
GRAY       = (100, 100, 100)
DARK_GRAY  = ( 40,  40,  40)
LIGHT_GRAY = (180, 180, 180)
YELLOW     = (255, 215,   0)
ORANGE     = (255, 140,   0)
PURPLE     = (180,   0, 255)
TEAL       = (  0, 180, 180)

TOOLBAR_BG         = ( 25,  25,  25)
TOOLBAR_BTN        = ( 55,  55,  55)
TOOLBAR_BTN_ACTIVE = (  0, 110, 180)
TOOLBAR_BTN_HOVER  = ( 75,  75,  75)
PANEL_BG           = ( 30,  30,  30)
PANEL_BORDER       = ( 70,  70,  70)

TOOLBAR_HEIGHT     = 64   # px
INIT_PANEL_WIDTH   = 240  # px  (initiative panel on right side)
GRID_SIZE          = 50   # px per grid cell
FEET_PER_CELL      = 5    # D&D 5e standard

LONG_PRESS_MS       = 500  # ms to trigger long-press context menu
LONG_PRESS_MOVE_PX  = 12   # px movement that aborts a long-press

# Player vision — how far fog is cleared around each character
# 6 cells = 30 ft (torch range); 2 extra cells = 10 ft dim-light falloff
VISION_RADIUS_PX = 6 * GRID_SIZE   # fully-clear radius per player
VISION_DIM_PX    = 2 * GRID_SIZE   # additional dim-light zone beyond that

# D&D 5e conditions: code -> (short label, chip colour, full name)
CONDITIONS = {
    'BLD': ('B',  (150, 150, 150), 'Blinded'),
    'CHM': ('C',  (255, 182, 193), 'Charmed'),
    'DEA': ('D',  (200, 200, 200), 'Deafened'),
    'FRT': ('F',  (255, 100,   0), 'Frightened'),
    'GRP': ('G',  (139,  69,  19), 'Grappled'),
    'INC': ('I',  (255, 255,   0), 'Incapacitated'),
    'INV': ('N',  (200, 200, 255), 'Invisible'),
    'PAR': ('Pa', (255,   0, 255), 'Paralyzed'),
    'POI': ('Po', (  0, 180,   0), 'Poisoned'),
    'PRN': ('Pr', (180, 120,  50), 'Prone'),
    'RST': ('R',  (255, 165,   0), 'Restrained'),
    'STN': ('S',  (255, 230,   0), 'Stunned'),
    'UNC': ('U',  ( 80,  80,  80), 'Unconscious'),
    'CON': ('K',  (  0, 200, 255), 'Concentrating'),
}
CONDITION_CODES = list(CONDITIONS.keys())

# D&D 5e token size presets: (radius px, display label)
SIZE_PRESETS = [
    (10,  'Tiny'),
    (15,  'Small'),
    (20,  'Medium'),
    (35,  'Large'),
    (50,  'Huge'),
    (75,  'Gargantuan'),
]
