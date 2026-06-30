# feedback.py — Button press-depress visual and thematic audio feedback

import pygame
import math
import wave
import io
import array as _array
import random as _random

# ── Sound synthesis helpers ───────────────────────────────────────────────────

_RATE = 44100
_rng  = _random.Random(7)   # deterministic so sound is identical each run


def _to_sound(buf):
    """Write stereo 16-bit PCM array to an in-memory WAV and return a Sound."""
    f = io.BytesIO()
    with wave.open(f, 'wb') as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(_RATE)
        wf.writeframes(buf.tobytes())
    f.seek(0)
    return pygame.mixer.Sound(f)


def _make_keyclick(ms=14, amplitude=0.60):
    """
    Mechanical key-click sound: fast noise burst + brief low-frequency thud.
    Sounds like pressing a physical keyboard key — not a beep.
    """
    n = int(_RATE * ms / 1000)
    max_a = int(32767 * amplitude)
    buf = _array.array('h')
    for i in range(n):
        frac = i / n
        # Sharp noise transient — very fast exponential decay (the "click")
        noise_env = math.exp(-28.0 * frac)
        noise = noise_env * _rng.uniform(-1.0, 1.0)
        # Subtle 90 Hz thud — the key bottoming out
        thud_env = math.exp(-14.0 * frac) * 0.22
        thud = thud_env * math.sin(math.tau * 90.0 * i / _RATE)
        val = max(-32768, min(32767, int(max_a * (noise + thud))))
        buf.append(val); buf.append(val)
    return _to_sound(buf)


def _make_tone(freq, ms, amplitude=0.35, envelope='decay'):
    n = int(_RATE * ms / 1000)
    max_a = int(32767 * amplitude)
    buf = _array.array('h')
    for i in range(n):
        t = i / _RATE
        frac = i / n
        if envelope == 'decay':
            env = 1.0 - frac
        elif envelope == 'bell':
            env = math.exp(-5.0 * frac)
        elif envelope == 'attack':
            peak = 0.15
            env = frac / peak if frac < peak else math.exp(-4.0 * (frac - peak))
        else:
            env = 1.0
        sample = max(-32768, min(32767, int(max_a * env * math.sin(math.tau * freq * t))))
        buf.append(sample); buf.append(sample)
    return _to_sound(buf)


def _make_chord(freqs, ms, amplitude=0.28):
    n = int(_RATE * ms / 1000)
    per = amplitude / len(freqs)
    buf = _array.array('h')
    for i in range(n):
        t = i / _RATE
        env = math.exp(-5.0 * i / n)
        s = sum(math.sin(math.tau * f * t) for f in freqs)
        sample = max(-32768, min(32767, int(32767 * per * env * s)))
        buf.append(sample); buf.append(sample)
    return _to_sound(buf)


def _make_pickup(ms=65, amplitude=0.68):
    """Wooden thunk — game-piece lifted off a table.
    Mid-low body tone with a brief noise transient at the attack."""
    n = int(_RATE * ms / 1000)
    max_a = int(32767 * amplitude)
    buf = _array.array('h')
    for i in range(n):
        frac = i / n
        # Body resonance at ~180 Hz with medium exponential decay
        body_env = math.exp(-9.0 * frac)
        body = body_env * math.sin(math.tau * 180.0 * i / _RATE)
        # Brief noise transient at the very start (the "pick" contact)
        noise_env = math.exp(-40.0 * frac)
        noise = noise_env * _rng.uniform(-1.0, 1.0) * 0.55
        val = max(-32768, min(32767, int(max_a * (body + noise))))
        buf.append(val); buf.append(val)
    return _to_sound(buf)


def _make_arpeggio(freqs, note_ms=55, amplitude=0.28):
    """Quick ascending arpeggio — portal / scene-transition feel."""
    n_per = int(_RATE * note_ms / 1000)
    max_a = int(32767 * amplitude)
    buf = _array.array('h')
    for freq in freqs:
        for i in range(n_per):
            frac = i / n_per
            env = math.exp(-4.5 * frac)
            sample = max(-32768, min(32767,
                         int(max_a * env * math.sin(math.tau * freq * i / _RATE))))
            buf.append(sample); buf.append(sample)
    return _to_sound(buf)


def _make_sweep(f0, f1, ms, amplitude=0.35):
    n = int(_RATE * ms / 1000)
    max_a = int(32767 * amplitude)
    buf = _array.array('h')
    phase = 0.0
    for i in range(n):
        frac = i / n
        freq = f0 + (f1 - f0) * frac
        env = 1.0 - frac
        sample = max(-32768, min(32767, int(max_a * env * math.sin(phase))))
        buf.append(sample); buf.append(sample)
        phase = (phase + math.tau * freq / _RATE) % math.tau
    return _to_sound(buf)


# ── SoundFX ───────────────────────────────────────────────────────────────────

class SoundFX:
    """
    Thematic UI sounds.

    Kinds:
        'click'   — generic toolbar/nav button (keyboard click noise)
        'select'  — ± steppers, toggles, low-impact (softer keyclick)
        'confirm' — Add / Save / Create (C-E-G chord)
        'cancel'  — Cancel / Close / dismiss
        'damage'  — HP loss, remove, delete
        'heal'    — HP restore, Full Heal
        'roll'    — Roll Initiative / dice
    """

    def __init__(self):
        self._sounds = {}
        self._ready  = False

    def init(self):
        """Generate all sounds. Call once, after pygame.mixer.init()."""
        try:
            pygame.mixer.set_num_channels(max(8, pygame.mixer.get_num_channels()))

            self._sounds = {
                # Generic click — noise-based key press sound
                'click':   _make_keyclick(ms=14, amplitude=0.60),
                # Stepper / toggle — lighter keyclick
                'select':  _make_keyclick(ms=10, amplitude=0.38),
                # Confirm — C-E-G major chord chime
                'confirm': _make_chord([523, 659, 784], 260, amplitude=0.30),
                # Cancel — muted lower tone
                'cancel':  _make_tone(294,  110, amplitude=0.28, envelope='decay'),
                # Damage — deep thud
                'damage':  _make_tone(90,   170, amplitude=0.55, envelope='decay'),
                # Heal — bright bell
                'heal':    _make_tone(1047, 330, amplitude=0.32, envelope='bell'),
                # Roll — high-to-low frequency sweep (dice tumble)
                'roll':    _make_sweep(700, 140, 250, amplitude=0.44),
                # Portal — C-E-G-C' ascending arpeggio (forward scene transition)
                'portal':        _make_arpeggio([262, 330, 392, 523], note_ms=55, amplitude=0.30),
                # Portal return — C'-G-E-C descending arpeggio (return portal)
                'portal_return': _make_arpeggio([523, 392, 330, 262], note_ms=55, amplitude=0.30),
                # Menu open — soft descending whoosh (menu slides into view)
                'menu_open': _make_sweep(520, 180, 75, amplitude=0.20),
                # Pickup — wooden thunk for lifting a token off the map
                'pickup':    _make_pickup(ms=65, amplitude=0.68),
            }
            for kind, vol in [('click',    0.80), ('select',    0.55),
                               ('confirm',  0.88), ('cancel',    0.60),
                               ('damage',   0.85), ('heal',      0.78),
                               ('roll',     0.82), ('portal',    0.85), ('portal_return', 0.85),
                               ('menu_open',0.65), ('pickup',    0.90)]:
                self._sounds[kind].set_volume(vol)
            self._ready = True
            print('[SoundFX] Ready — 11 sounds generated')
        except Exception as e:
            print(f'[SoundFX] init failed: {e}')

    def play(self, kind):
        """Play the named sound on any free mixer channel."""
        if not self._ready or kind is None:
            return
        snd = self._sounds.get(kind)
        if snd:
            try:
                snd.play()
            except Exception as e:
                print(f'[SoundFX] play({kind}) error: {e}')


# ── PressFX ───────────────────────────────────────────────────────────────────

class PressFX:
    """
    Brief white-flash overlay on a clicked button, sized to the actual button rect.

    Call trigger(rect) with the button's exact pygame.Rect, or trigger_pos(pos)
    when only the click position is available.  Call draw(surface) once per frame
    after all other UI is drawn.
    """

    DURATION_MS = 130
    START_ALPHA = 160   # white overlay alpha at t=0

    def __init__(self):
        self._effects = []   # list of (rect, start_ticks)

    def trigger(self, rect):
        """Flash the exact button rect."""
        self._effects.append((pygame.Rect(rect), pygame.time.get_ticks()))

    def trigger_pos(self, pos, w=88, h=42):
        """Flash a rect centred on a screen position (fallback when no rect is known)."""
        r = pygame.Rect(0, 0, w, h)
        r.center = pos
        self._effects.append((r, pygame.time.get_ticks()))

    def draw(self, surface):
        now = pygame.time.get_ticks()
        self._effects = [(r, t) for r, t in self._effects
                         if now - t < self.DURATION_MS]
        for rect, start in self._effects:
            frac  = (now - start) / self.DURATION_MS
            alpha = int(self.START_ALPHA * (1.0 - frac))
            if alpha <= 0:
                continue
            ov = pygame.Surface((rect.w, rect.h), pygame.SRCALPHA)
            ov.fill((255, 255, 255, alpha))
            surface.blit(ov, rect.topleft)


# ── Module-level singletons ───────────────────────────────────────────────────

sound_fx = SoundFX()
press_fx = PressFX()
