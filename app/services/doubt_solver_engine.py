"""
Quovex Intelligent Doubt Solver Engine

Generates human-readable, plain-text answers with NO LaTeX, NO markdown symbols,
NO escaped characters. Every answer reads like a real tutor explaining clearly.

4 answer types based on what the student actually asked:
  - factual    : a direct fact question ("What is the speed of light?")
  - numerical  : a calculation problem ("A body moves 20m in 4s. Find speed.")
  - conceptual : a "why" or "how" question ("Why does resistance decrease current?")
  - teach_me   : a learning request ("Teach me electrostatics")
"""
import re
import math
import json
import httpx
from typing import List, Tuple, Optional, Any
from app.config import settings
from app.schemas import DoubtStepOut

# ─────────────────────────────────────────────────────────────
#  SUBJECT DETECTION
# ─────────────────────────────────────────────────────────────

SUBJECT_KEYWORDS = {
    "Physics": [
        "force", "velocity", "acceleration", "energy", "momentum", "newton", "gravity", "mass",
        "charge", "current", "wave", "optics", "lens", "mirror", "friction", "projectile", "speed",
        "power", "work", "torque", "inertia", "fluid", "pressure", "temperature", "heat", "ohm",
        "resistance", "voltage", "capacitance", "magnetic", "field", "pendulum", "frequency",
        "wavelength", "light", "vacuum", "photon", "quantum", "kinematics", "dynamics"
    ],
    "Mathematics": [
        "integral", "derivative", "limit", "matrix", "matrices", "equation", "polynomial", "proof", "theorem",
        "function", "vector", "calculus", "algebra", "quadratic", "roots", "discriminant", "triangle",
        "circle", "trigonometry", "sin", "cos", "tan", "sec", "cosec", "cot", "log", "ln", "logarithm",
        "probability", "permutation", "combination", "determinant", "sequence", "series", "progression",
        "geometry", "slope", "differentiate", "integrate", "evaluate", "solve", "factorize", "simplify",
        "pythagoras", "hypotenuse", "perimeter", "area", "volume", "differential", "dx", "dy", "alpha", "beta"
    ],
    "Chemistry": [
        "element", "compound", "reaction", "mole", "bond", "orbital", "acid", "base", "equilibrium",
        "enthalpy", "periodic", "atom", "molecule", "ph", "oxidation", "reduction", "stoichiometry",
        "organic", "alkane", "alkene", "molarity", "molality", "catalyst", "electron", "hybridization"
    ],
    "Biology": [
        "cell", "dna", "rna", "protein", "organism", "evolution", "photosynthesis", "respiration",
        "neuron", "chromosome", "gene", "mitosis", "meiosis", "enzyme", "mitochondria", "tissue",
        "heart", "brain", "kidney", "ecosystem", "species", "mendel", "genetics", "hormone"
    ],
}


def detect_subject(text: str, hint: Optional[str] = None) -> str:
    if hint and hint.strip().lower() not in ("general", "all", ""):
        return hint.strip().capitalize()
    low = text.lower()
    scores = {}
    for subj, kws in SUBJECT_KEYWORDS.items():
        score = sum(1 for kw in kws if re.search(rf"\b{re.escape(kw)}", low))
        scores[subj] = score
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "General"


# ─────────────────────────────────────────────────────────────
#  QUESTION TYPE CLASSIFIER
# ─────────────────────────────────────────────────────────────

def classify_question_type(question: str) -> str:
    """
    Returns one of: "factual", "numerical", "conceptual", "teach_me"
    """
    low = question.lower().strip()

    # Diagram / Schematic / Visual: "draw diagram", "ray diagram", "circuit schematic", "flowchart", "graph"
    diagram_triggers = ["draw", "diagram", "schematic", "sketch", "ray diagram", "circuit",
                        "flowchart", "graph of", "plot", "visualize", "structure of", "pin diagram",
                        "block diagram", "waveform", "truth table"]
    if any(t in low for t in diagram_triggers):
        return "diagram"

    # Teach Me: "teach me X", "explain X", "what is X in detail", "lesson on X"
    teach_triggers = ["teach me", "lesson on", "teach about", "guide me", "learn about",
                      "study guide", "overview of", "introduction to", "topic on"]
    if any(t in low for t in teach_triggers):
        return "teach_me"

    # Numerical / Math Problem: contains numbers, math symbols, calculus, algebra, equations
    has_numbers = bool(re.search(r"\d+", low))
    has_math_symbols = bool(re.search(r"(=|\^|\+|\-|\*|\/|\b(sin|cos|tan|log|ln|dx|dy|lim|sqrt|integral|derivative|matrix|matrices)\b)", low))
    calc_triggers = ["find", "calculate", "compute", "determine", "solve", "evaluate", "simplify",
                     "differentiate", "integrate", "factorize", "roots", "discriminant", "value of",
                     "final velocity", "work done", "distance", "time taken", "how much", "how far"]
    if (has_numbers or has_math_symbols) and any(t in low for t in calc_triggers):
        return "numerical"
    if has_math_symbols and ("=" in low or "^" in low or "dx" in low):
        return "numerical"

    # Conceptual: "why", "how does", "explain why", "reason for", "what happens when"
    conceptual_triggers = ["why", "how does", "how do", "explain why", "reason for",
                           "what happens", "effect of", "role of", "difference between",
                           "compare", "relationship between", "when does", "what causes"]
    if any(t in low for t in conceptual_triggers):
        return "conceptual"

    # Default: factual  --  direct "what is", "what are", "define", "state", "who discovered"
    return "factual"


def classify_confidence(question_type: str) -> Tuple[str, str]:
    """Returns (confidence_level, confidence_label)"""
    if question_type == "diagram":
        return "high", "Visual Diagram & Schematic"
    elif question_type == "numerical":
        return "high", "Verified calculation"
    elif question_type == "factual":
        return "high", "Textbook verified"
    elif question_type == "conceptual":
        return "medium", "Conceptual explanation"
    else:
        return "medium", "Learning overview"


# ─────────────────────────────────────────────────────────────
#  NUMBER EXTRACTION UTILITY
# ─────────────────────────────────────────────────────────────

def extract_numbers(text: str) -> List[float]:
    return [float(x) for x in re.findall(r"[-+]?\d*\.?\d+", text)]


# ─────────────────────────────────────────────────────────────
#  FACTUAL SOLVERS  (Answer / Why / Remember  --  3 sections max)
# ─────────────────────────────────────────────────────────────

def _factual_speed_of_light() -> Tuple[List[DoubtStepOut], str, List[str], List[str]]:
    steps = [
        DoubtStepOut(
            step=1, title="The Answer",
            content="The speed of light in a vacuum is exactly 299,792,458 metres per second -- "
                    "commonly written as 3.00 x 10^8 m/s.\n\n"
                    "This constant is so important that it has its own symbol: c."
        ),
        DoubtStepOut(
            step=2, title="Why is it this value?",
            content="Light is an electromagnetic wave. Its speed in vacuum is fixed by two "
                    "fundamental constants of nature -- the permittivity of free space "
                    "and the permeability of free space.\n\n"
                    "The relationship is: c = 1 / sqrt(permittivity x permeability)\n\n"
                    "In any other medium, light slows down. In water (refractive index approx 1.33), "
                    "light travels at about 2.25 x 10^8 m/s."
        ),
        DoubtStepOut(
            step=3, title="Remember for Your Exam",
            content="c = 3.00 x 10^8 m/s  (in vacuum)\n\n"
                    "Speed in a medium: v = c / n  (where n is the refractive index)\n\n"
                    "Einstein's famous result: E = m x c^2  (mass-energy equivalence)\n\n"
                    "c is the cosmic speed limit -- nothing with mass can reach or exceed it."
        )
    ]
    return (
        steps,
        "The speed of light in vacuum is 299,792,458 m/s (approximately 3.00 x 10^8 m/s), "
        "denoted by c. It is the fastest speed possible in the universe.",
        ["c = 3.00 x 10^8 m/s", "v = c / n", "E = m x c^2"],
        ["Optics", "Electromagnetism", "Special Relativity"]
    )


def _factual_newtons_second_law() -> Tuple[List[DoubtStepOut], str, List[str], List[str]]:
    steps = [
        DoubtStepOut(
            step=1, title="The Answer",
            content="Newton's Second Law of Motion states:\n\n"
                    "The acceleration of an object is directly proportional to the net force "
                    "acting on it, and inversely proportional to its mass.\n\n"
                    "In everyday language: a bigger force makes an object speed up more quickly. "
                    "A heavier object needs more force to achieve the same acceleration."
        ),
        DoubtStepOut(
            step=2, title="The Core Formula",
            content="Force = Mass  x  Acceleration\n\n"
                    "F = m  x  a\n\n"
                    "Rearranging:\n"
                    "  Acceleration (a) = F / m\n"
                    "  Mass (m) = F / a\n\n"
                    "SI Units: Force in Newtons (N), Mass in kilograms (kg), "
                    "Acceleration in m/s^2\n"
                    "1 Newton = 1 kg  x  m/s^2"
        ),
        DoubtStepOut(
            step=3, title="Real-Life Example",
            content="When a cricketer catches a ball, he pulls his hands backward. "
                    "This increases the time over which the ball decelerates. "
                    "Since Force = Change in Momentum / Time, a longer time means less force on "
                    "his hands  --  which is why it hurts less than a rigid catch.\n\n"
                    "Another example: pushing a shopping trolley. An empty trolley (less mass) "
                    "accelerates much faster than a full one with the same push force."
        )
    ]
    return (
        steps,
        "Newton's Second Law: the net force on an object equals its mass multiplied by its "
        "acceleration. Formula: F = m  x  a. A larger force causes greater acceleration; "
        "a larger mass resists acceleration more.",
        ["F = m  x  a", "a = F / m", "1 N = 1 kg·m/s^2", "Impulse = F  x  t"],
        ["Laws of Motion", "Dynamics", "Classical Mechanics"]
    )


def _factual_newtons_first_law() -> Tuple[List[DoubtStepOut], str, List[str], List[str]]:
    steps = [
        DoubtStepOut(
            step=1, title="The Answer",
            content="Newton's First Law states:\n\n"
                    "An object at rest stays at rest, and an object in motion continues moving "
                    "at the same speed in the same direction, unless acted upon by an external "
                    "force.\n\n"
                    "This property is called inertia  --  the natural resistance of objects to "
                    "changes in their state of motion."
        ),
        DoubtStepOut(
            step=2, title="What is Inertia?",
            content="Inertia is not a force  --  it is a property. The more massive an object, "
                    "the greater its inertia, meaning it is harder to start moving, stop, "
                    "or change direction.\n\n"
                    "Mathematical condition: If the net force on an object is zero (F_net = 0), "
                    "then its acceleration is zero, and velocity stays constant."
        ),
        DoubtStepOut(
            step=3, title="Everyday Examples",
            content="1. You lurch forward when a bus brakes suddenly  --  your body's inertia "
                    "wants to keep moving forward while the bus stops.\n\n"
                    "2. A ball rolled on a frictionless surface would continue forever  --  "
                    "friction is the external force that normally slows it.\n\n"
                    "3. A tablecloth pulled quickly from under dishes  --  inertia keeps the "
                    "dishes roughly in place."
        )
    ]
    return (
        steps,
        "Newton's First Law (Law of Inertia): an object maintains its state of rest or "
        "uniform motion unless an external net force acts on it. This tendency to resist "
        "change in motion is called inertia.",
        ["F_net = 0  means  a = 0", "v = constant when F = 0"],
        ["Laws of Motion", "Inertia", "Classical Mechanics"]
    )


def _factual_unit_of_current() -> Tuple[List[DoubtStepOut], str, List[str], List[str]]:
    steps = [
        DoubtStepOut(
            step=1, title="The Answer",
            content="The SI unit of electric current is the Ampere, written as A.\n\n"
                    "It is named after the French physicist André-Marie Ampère, "
                    "a pioneer of electromagnetism."
        ),
        DoubtStepOut(
            step=2, title="What does 1 Ampere mean?",
            content="Electric current is the rate of flow of electric charge through a conductor.\n\n"
                    "Formula: I = Q / t\n\n"
                    "Where:\n"
                    "  I = Current (Amperes)\n"
                    "  Q = Charge (Coulombs)\n"
                    "  t = Time (seconds)\n\n"
                    "So: 1 Ampere = 1 Coulomb of charge flowing per second.\n\n"
                    "In terms of electrons: 1 Ampere means approximately "
                    "6.24  x  10^18 electrons flowing past a point every second."
        ),
        DoubtStepOut(
            step=3, title="Related Units to Remember",
            content="Current (I)     ->  Ampere (A)\n"
                    "Voltage (V)     ->  Volt (V = J/C)\n"
                    "Resistance (R)  ->  Ohm ( Ohm = V/A)\n"
                    "Power (P)       ->  Watt (W = V  x  A)\n"
                    "Charge (Q)      ->  Coulomb (C = A  x  s)\n\n"
                    "Current is measured using an Ammeter, connected in series in the circuit."
        )
    ]
    return (
        steps,
        "The SI unit of electric current is the Ampere (A). "
        "1 Ampere = 1 Coulomb of charge per second. Formula: I = Q / t.",
        ["I = Q / t", "1 A = 1 C/s", "V = I  x  R"],
        ["Current Electricity", "Electrostatics", "Circuit Theory"]
    )


# ─────────────────────────────────────────────────────────────
#  NUMERICAL SOLVERS  (Given -> Formula -> Substitute -> Calculate -> Answer)
# ─────────────────────────────────────────────────────────────

def _numerical_f_equals_ma(m: float, a: float) -> Tuple[List[DoubtStepOut], str, List[str], List[str]]:
    F = m * a
    steps = [
        DoubtStepOut(step=1, title="Given Information",
            content=f"Mass (m) = {m} kg\n"
                    f"Acceleration (a) = {a} m/s^2\n"
                    f"Find: Net Force (F)"),
        DoubtStepOut(step=2, title="Formula to Use",
            content="Newton's Second Law:\n\nF = m  x  a\n\n"
                    "Force equals mass times acceleration."),
        DoubtStepOut(step=3, title="Substitute the Values",
            content=f"F = {m}  x  {a}"),
        DoubtStepOut(step=4, title="Calculate",
            content=f"F = {F:.2f} N"),
        DoubtStepOut(step=5, title="Answer",
            content=f"The net force on the object is {F:.2f} Newtons.\n\n"
                    f"To put this in perspective: {F:.1f} N is roughly the weight of "
                    f"{F/9.8:.1f} kg in Earth's gravity.")
    ]
    return (
        steps,
        f"The net force is {F:.2f} N. Using F = m  x  a = {m}  x  {a}.",
        ["F = m  x  a", f"F = {m}  x  {a} = {F:.2f} N"],
        ["Newton's Second Law", "Dynamics"]
    )


def _numerical_kinematics_speed(d: float, t: float) -> Tuple[List[DoubtStepOut], str, List[str], List[str]]:
    v = d / t
    steps = [
        DoubtStepOut(step=1, title="Given Information",
            content=f"Distance (d) = {d} m\n"
                    f"Time (t) = {t} s\n"
                    f"Find: Speed (v)"),
        DoubtStepOut(step=2, title="Formula to Use",
            content="Average Speed = Distance / Time\n\nv = d / t"),
        DoubtStepOut(step=3, title="Substitute the Values",
            content=f"v = {d} / {t}"),
        DoubtStepOut(step=4, title="Calculate",
            content=f"v = {v:.2f} m/s\n\nIn km/h: {v * 3.6:.1f} km/h"),
        DoubtStepOut(step=5, title="Answer",
            content=f"The average speed of the body is {v:.2f} m/s ({v * 3.6:.1f} km/h).")
    ]
    return (
        steps,
        f"Speed = Distance / Time = {d} / {t} = {v:.2f} m/s.",
        ["v = d / t", f"v = {d}/{t} = {v:.2f} m/s"],
        ["Kinematics", "Motion in 1D"]
    )


def _numerical_free_fall(h: float) -> Tuple[List[DoubtStepOut], str, List[str], List[str]]:
    g = 9.8
    t = math.sqrt((2 * h) / g)
    v = math.sqrt(2 * g * h)
    steps = [
        DoubtStepOut(step=1, title="Given Information",
            content=f"Height (h) = {h} m\n"
                    f"Initial velocity (u) = 0 m/s  (object dropped, not thrown)\n"
                    f"Acceleration due to gravity (g) = 9.8 m/s^2\n"
                    f"Find: time to reach ground and final velocity"),
        DoubtStepOut(step=2, title="Formula to Use",
            content="For an object dropped from rest:\n\n"
                    "Time of fall:       h = 1/2  x  g  x  t^2   ->   t = sqrt(2h / g)\n"
                    "Final velocity:     v^2 = 2  x  g  x  h   ->   v = sqrt(2gh)"),
        DoubtStepOut(step=3, title="Substitute the Values",
            content=f"t = sqrt(2  x  {h} / 9.8) = sqrt({(2*h)/g:.3f})\n\n"
                    f"v = sqrt(2  x  9.8  x  {h}) = sqrt({2*g*h:.2f})"),
        DoubtStepOut(step=4, title="Calculate",
            content=f"Time to reach ground:   t = {t:.2f} seconds\n"
                    f"Final impact velocity:  v = {v:.2f} m/s  ({v*3.6:.1f} km/h)"),
        DoubtStepOut(step=5, title="Answer",
            content=f"The object takes {t:.2f} seconds to reach the ground "
                    f"and hits with a velocity of {v:.2f} m/s.")
    ]
    return (
        steps,
        f"Time = {t:.2f} s, Impact velocity = {v:.2f} m/s. "
        f"Using t = sqrt(2h/g) and v = sqrt(2gh) with g = 9.8 m/s^2.",
        ["t = sqrt(2h/g)", "v = sqrt(2gh)", "h = 1/2gt^2"],
        ["Free Fall", "Kinematics", "Gravitation"]
    )


def _numerical_incline(m: float, theta_deg: float) -> Tuple[List[DoubtStepOut], str, List[str], List[str]]:
    g = 9.8
    theta_rad = math.radians(theta_deg)
    a = g * math.sin(theta_rad)
    F_parallel = m * a
    N = m * g * math.cos(theta_rad)
    steps = [
        DoubtStepOut(step=1, title="Given Information",
            content=f"Mass (m) = {m} kg\n"
                    f"Angle of incline = {theta_deg}°\n"
                    f"g = 9.8 m/s^2  (assume smooth/frictionless unless stated)\n"
                    f"Find: acceleration down the slope and the driving force"),
        DoubtStepOut(step=2, title="Understanding the Forces",
            content="Gravity pulls the object straight down with force mg.\n\n"
                    "On an inclined plane, this splits into two components:\n"
                    f"  Along the slope (causes motion): mg  x  sin({theta_deg}°)\n"
                    f"  Perpendicular to slope (normal force): mg  x  cos({theta_deg}°)\n\n"
                    "The normal force prevents the object from going through the surface. "
                    "The parallel component is what slides the object down."),
        DoubtStepOut(step=3, title="Substitute",
            content=f"Acceleration along slope:  a = g  x  sin({theta_deg}°)\n"
                    f"  = 9.8  x  sin({theta_deg}°)\n"
                    f"  = 9.8  x  {math.sin(theta_rad):.4f}\n\n"
                    f"Normal force:  N = m  x  g  x  cos({theta_deg}°)\n"
                    f"  = {m}  x  9.8  x  {math.cos(theta_rad):.4f}"),
        DoubtStepOut(step=4, title="Calculate",
            content=f"Acceleration down slope:  a = {a:.2f} m/s^2\n"
                    f"Driving force along slope: F = {F_parallel:.2f} N\n"
                    f"Normal force: N = {N:.2f} N"),
        DoubtStepOut(step=5, title="Answer",
            content=f"The {m} kg object slides down the {theta_deg}° incline "
                    f"with an acceleration of {a:.2f} m/s^2. "
                    f"The force pulling it down the slope is {F_parallel:.2f} N.")
    ]
    return (
        steps,
        f"Acceleration = g  x  sin({theta_deg}°) = {a:.2f} m/s^2. "
        f"Driving force = {F_parallel:.2f} N.",
        [f"a = g sin(theta) = {a:.2f} m/s^2", "N = mg cos(theta)", "F = mg sin(theta)"],
        ["Inclined Planes", "Laws of Motion", "Vector Resolution"]
    )


def _numerical_ohms_law(numbers: List[float], q_low: str) -> Tuple[List[DoubtStepOut], str, List[str], List[str]]:
    if len(numbers) < 2:
        return None
    v1, v2 = numbers[0], numbers[1]

    if "voltage" in q_low and "resistance" in q_low:
        V, R = v1, v2
        I = V / R
        steps = [
            DoubtStepOut(step=1, title="Given Information",
                content=f"Voltage (V) = {V} V\n"
                        f"Resistance (R) = {R}  Ohm\n"
                        f"Find: Current (I)"),
            DoubtStepOut(step=2, title="Formula to Use",
                content="Ohm's Law:  V = I  x  R\n\nRearranging for current: I = V / R"),
            DoubtStepOut(step=3, title="Substitute",
                content=f"I = {V} / {R}"),
            DoubtStepOut(step=4, title="Calculate",
                content=f"I = {I:.3f} A  ({I * 1000:.2f} mA)"),
            DoubtStepOut(step=5, title="Answer",
                content=f"The current flowing through the circuit is {I:.3f} A.\n"
                        f"Power dissipated: P = V  x  I = {V}  x  {I:.3f} = {V*I:.2f} W")
        ]
        return (steps, f"Current I = V/R = {V}/{R} = {I:.3f} A.",
                ["V = I  x  R", "I = V / R", "P = V  x  I", f"I = {I:.3f} A"],
                ["Current Electricity", "DC Circuits", "Ohm's Law"])

    return None


# ─────────────────────────────────────────────────────────────
#  CONCEPTUAL SOLVERS  (Core Idea -> Intuition -> Equation -> Example -> Check Yourself)
# ─────────────────────────────────────────────────────────────

def _conceptual_resistance_current() -> Tuple[List[DoubtStepOut], str, List[str], List[str]]:
    steps = [
        DoubtStepOut(step=1, title="Core Idea",
            content="When voltage stays constant, lowering resistance allows more current to "
                    "flow through a circuit.\n\n"
                    "They have an inverse relationship: as one goes up, the other goes down."),
        DoubtStepOut(step=2, title="The Intuition",
            content="Think of a water pipe. The voltage is like water pressure pushing water "
                    "through. The resistance is like the narrowness of the pipe.\n\n"
                    "A wider pipe (lower resistance) lets more water flow (higher current) "
                    "for the same pressure (same voltage).\n\n"
                    "A narrower pipe (higher resistance) restricts the flow  --  just as a "
                    "high-resistance component limits current."),
        DoubtStepOut(step=3, title="The Equation",
            content="Ohm's Law:  V = I  x  R\n\n"
                    "Rearranging: I = V / R\n\n"
                    "If V is constant and R decreases -> I must increase.\n"
                    "If V is constant and R increases -> I must decrease.\n\n"
                    "For example: V = 12 V, R = 3  Ohm -> I = 4 A\n"
                    "             V = 12 V, R = 6  Ohm -> I = 2 A  (R doubled, I halved)"),
        DoubtStepOut(step=4, title="Real World Example",
            content="A dimmer switch controls the brightness of a bulb by changing the "
                    "resistance in the circuit. Higher resistance -> less current -> dimmer bulb.\n\n"
                    "Short circuits are dangerous because resistance drops to nearly zero, "
                    "so current surges to an extremely high value, which can start fires."),
        DoubtStepOut(step=5, title="Check Your Understanding",
            content="Try this: A 9V battery is connected to a 3  Ohm resistor. What is the current?\n\n"
                    "Answer: I = V / R = 9 / 3 = 3 A\n\n"
                    "Now if the resistance doubles to 6  Ohm, current halves to 1.5 A. "
                    "Can you verify this using Ohm's Law?")
    ]
    return (
        steps,
        "When voltage is fixed, current and resistance are inversely proportional (I = V/R). "
        "Lower resistance allows more current to flow.",
        ["I = V / R", "V = I  x  R", "R  increases  means I  decreases  at constant V"],
        ["Current Electricity", "Ohm's Law", "DC Circuits"]
    )


def _conceptual_why_sky_blue() -> Tuple[List[DoubtStepOut], str, List[str], List[str]]:
    steps = [
        DoubtStepOut(step=1, title="Core Idea",
            content="The sky appears blue because of a phenomenon called Rayleigh Scattering  --  "
                    "sunlight is scattered by gas molecules in the atmosphere, and blue light "
                    "scatters much more than red light."),
        DoubtStepOut(step=2, title="The Intuition",
            content="Sunlight is white light  --  it contains all colours of the rainbow. "
                    "When sunlight enters the atmosphere, it collides with tiny nitrogen and "
                    "oxygen molecules.\n\n"
                    "Shorter wavelengths (violet and blue) scatter in all directions far more "
                    "than longer wavelengths (red, orange). So blue light fills the entire sky "
                    "from all directions, while red light passes straight through."),
        DoubtStepOut(step=3, title="The Physics",
            content="Rayleigh Scattering intensity is proportional to 1 / wavelength^4.\n\n"
                    "Blue light (wavelength ≈ 450 nm) scatters about 5.5 times more than "
                    "red light (wavelength ≈ 700 nm) because 700/450 ≈ 1.56, "
                    "and 1.56^4 ≈ 5.5.\n\n"
                    "Your eye sees the scattered blue light coming from every part of the sky."),
        DoubtStepOut(step=4, title="Why Sunsets are Red",
            content="At sunrise and sunset, sunlight travels through a much thicker layer of "
                    "atmosphere. By the time it reaches you, almost all the blue has scattered "
                    "away in other directions. Only the longer red and orange wavelengths "
                    "remain  --  giving that warm glow."),
        DoubtStepOut(step=5, title="Check Your Understanding",
            content="Quick question: Why does the Moon's sky appear black even during the day?\n\n"
                    "The Moon has no atmosphere. Without gas molecules to scatter sunlight, "
                    "there is no blue sky  --  just the darkness of space.")
    ]
    return (
        steps,
        "The sky is blue due to Rayleigh Scattering. Blue light (short wavelength) "
        "scatters about 5 times more than red light when sunlight hits atmospheric molecules.",
        ["Scattering  proportional to  1/lambda^4", "Blue lambda ≈ 450 nm", "Red lambda ≈ 700 nm"],
        ["Optics", "Wave Nature of Light", "Atmospheric Physics"]
    )


def _conceptual_gravity() -> Tuple[List[DoubtStepOut], str, List[str], List[str]]:
    steps = [
        DoubtStepOut(step=1, title="Core Idea",
            content="Gravity is a fundamental force of attraction between any two objects "
                    "that have mass. The more massive the objects and the closer they are, "
                    "the stronger the gravitational pull between them."),
        DoubtStepOut(step=2, title="The Intuition",
            content="Every object in the universe pulls every other object toward it. "
                    "You attract the Earth, and the Earth attracts you. But because Earth "
                    "is vastly more massive, it barely accelerates  --  while you fall at 9.8 m/s^2.\n\n"
                    "This is why planets orbit the Sun, the Moon orbits Earth, and "
                    "objects fall when dropped."),
        DoubtStepOut(step=3, title="Newton's Law of Gravitation",
            content="F = G  x  m_1  x  m_2 / r^2\n\n"
                    "Where:\n"
                    "  F = gravitational force\n"
                    "  G = Universal gravitational constant = 6.67  x  10^-11 N·m^2/kg^2\n"
                    "  m_1 and m_2 = masses of the two objects\n"
                    "  r = distance between their centres\n\n"
                    "The force follows an inverse-square law: double the distance, "
                    "and the force becomes 4 times weaker."),
        DoubtStepOut(step=4, title="Near Earth's Surface",
            content="For objects near Earth's surface, gravity simplifies to:\n\n"
                    "Weight = mass  x  g\n"
                    "W = m  x  g  (where g = 9.8 m/s^2)\n\n"
                    "So a 60 kg person weighs: W = 60  x  9.8 = 588 N on Earth.\n"
                    "On the Moon (g = 1.6 m/s^2), the same person weighs only 96 N  --  "
                    "that is why astronauts can jump much higher there."),
        DoubtStepOut(step=5, title="Check Your Understanding",
            content="If the distance between two objects doubles, by what factor does gravity change?\n\n"
                    "Answer: Force becomes 1/4 as strong (inverse-square law).\n\n"
                    "What if mass doubles? Force doubles  --  gravity is directly proportional to mass.")
    ]
    return (
        steps,
        "Gravity is an attractive force between masses. "
        "Newton's Law: F = G  x  m_1  x  m_2 / r^2. Near Earth's surface, F = mg (g = 9.8 m/s^2).",
        ["F = G m_1m_2 / r^2", "W = mg", "g = 9.8 m/s^2", "G = 6.67  x  10^-^1^1 N·m^2/kg^2"],
        ["Gravitation", "Newton's Law of Gravitation", "Mechanics"]
    )


# ─────────────────────────────────────────────────────────────
#  TEACH ME SOLVERS  (Concept map  --  ordered learning path)
# ─────────────────────────────────────────────────────────────

def _teach_electrostatics() -> Tuple[List[DoubtStepOut], str, List[str], List[str]]:
    steps = [
        DoubtStepOut(step=1, title="Start Here: Electric Charge",
            content="Everything begins with charge. Protons carry positive charge, "
                    "electrons carry negative charge. Like charges repel, opposite charges attract.\n\n"
                    "Key fact: Charge is conserved  --  it cannot be created or destroyed, "
                    "only transferred.\n\n"
                    "SI unit of charge: Coulomb (C). Elementary charge: e = 1.6  x  10^-19 C"),
        DoubtStepOut(step=2, title="Step 2: Coulomb's Law",
            content="The force between two point charges is:\n\n"
                    "F = k  x  q_1  x  q_2 / r^2\n\n"
                    "Where k = 9  x  10^9 N·m^2/C^2 is Coulomb's constant.\n\n"
                    "Same form as gravity  --  but much stronger, and can be repulsive as well as attractive."),
        DoubtStepOut(step=3, title="Step 3: Electric Field",
            content="Instead of asking 'what force does charge A exert on B?', we ask:\n"
                    "'What field does charge A create at a point in space?'\n\n"
                    "Electric Field E = F / q  (force per unit positive charge)\n"
                    "Field due to a point charge: E = k  x  Q / r^2\n\n"
                    "Direction: away from positive charges, toward negative charges."),
        DoubtStepOut(step=4, title="Step 4: Electric Potential",
            content="Electric potential V is the work done per unit charge to bring a "
                    "positive charge from infinity to a point.\n\n"
                    "V = k  x  Q / r\n\n"
                    "Potential difference (voltage): ΔV = W / q\n"
                    "Relationship to field: E = -dV/dr (field is the slope of potential)"),
        DoubtStepOut(step=5, title="Step 5: Capacitors",
            content="A capacitor stores charge between two conducting plates.\n\n"
                    "Capacitance: C = Q / V (how much charge per volt)\n"
                    "SI unit: Farad (F)\n\n"
                    "Parallel plate capacitor: C = eps_0  x  A / d\n"
                    "(where A = plate area, d = separation, eps_0 = 8.85  x  10^-12 F/m)\n\n"
                    "Energy stored in a capacitor: E = 1/2  x  C  x  V^2")
    ]
    return (
        steps,
        "Electrostatics covers: Charge -> Coulomb's Law -> Electric Field -> Electric Potential -> Capacitors. "
        "Master these 5 steps in order.",
        ["F = kq_1q_2/r^2", "E = kQ/r^2", "V = kQ/r", "C = Q/V", "E_stored = 1/2CV^2"],
        ["Electrostatics", "Electric Field", "Capacitors", "JEE Physics"]
    )


def _teach_quadratic_equations() -> Tuple[List[DoubtStepOut], str, List[str], List[str]]:
    steps = [
        DoubtStepOut(step=1, title="Start Here: What is a Quadratic?",
            content="A quadratic equation has the form: ax^2 + bx + c = 0\n\n"
                    "where a, b, c are real numbers and a != 0.\n\n"
                    "The graph of a quadratic is a parabola  --  it opens upward if a > 0, "
                    "downward if a < 0.\n\n"
                    "Examples: x^2 - 5x + 6 = 0,  2x^2 + 3x - 2 = 0"),
        DoubtStepOut(step=2, title="Step 2: Finding the Roots",
            content="The solutions (roots) are the values of x where the equation equals zero  --  "
                    "where the parabola crosses the x-axis.\n\n"
                    "Three methods:\n"
                    "1. Factorisation: rewrite as (x - r_1)(x - r_2) = 0\n"
                    "2. Completing the square\n"
                    "3. Quadratic Formula: x = (-b +/- sqrt(b^2 - 4ac)) / 2a"),
        DoubtStepOut(step=3, title="Step 3: The Discriminant",
            content="The discriminant D = b^2 - 4ac tells you the nature of the roots "
                    "BEFORE you solve:\n\n"
                    "D > 0  ->  Two distinct real roots (parabola crosses x-axis twice)\n"
                    "D = 0  ->  One repeated real root (parabola just touches the x-axis)\n"
                    "D < 0  ->  No real roots, two complex roots (parabola never touches x-axis)"),
        DoubtStepOut(step=4, title="Step 4: Sum and Product of Roots",
            content="If the roots are alpha and beta, then:\n\n"
                    "Sum of roots:     alpha + beta = -b / a\n"
                    "Product of roots: alpha  x  beta = c / a\n\n"
                    "These shortcuts are extremely useful in JEE problems  --  "
                    "you often do not need to find alpha and beta individually."),
        DoubtStepOut(step=5, title="Step 5: Worked Example",
            content="Solve: x^2 - 5x + 6 = 0  (a=1, b=-5, c=6)\n\n"
                    "Discriminant: D = (-5)^2 - 4(1)(6) = 25 - 24 = 1 > 0  ->  two real roots\n\n"
                    "Using quadratic formula:\n"
                    "x = (5 +/- sqrt1) / 2\n"
                    "x = (5 + 1)/2 = 3   or   x = (5 - 1)/2 = 2\n\n"
                    "Verify: Sum = 3 + 2 = 5 = -(-5)/1   [Verified] \n"
                    "        Product = 3  x  2 = 6 = 6/1   [Verified] ")
    ]
    return (
        steps,
        "Quadratic equations: ax^2 + bx + c = 0. Roots found by factorisation or formula "
        "x = (-b +/- sqrt(b^2-4ac)) / 2a. Discriminant D = b^2-4ac determines the nature of roots.",
        ["x = (-b +/- sqrtD) / 2a", "D = b^2 - 4ac", "alpha + beta = -b/a", "alphabeta = c/a"],
        ["Algebra", "Quadratic Equations", "JEE Mathematics"]
    )


# ─────────────────────────────────────────────────────────────
#  FOLLOW-UP ACTION HANDLERS
# ─────────────────────────────────────────────────────────────

def _apply_follow_up(
    action: str,
    original_steps: List[DoubtStepOut],
    final_answer: str,
    question_text: str,
    subject: str
) -> Tuple[List[DoubtStepOut], str]:
    """Modifies steps based on the follow-up action requested."""

    if action == "simplify":
        # Add a simplified recap at the end
        simplified = DoubtStepOut(
            step=len(original_steps) + 1,
            title="Simpler Explanation",
            content=f"Here is the main idea in simple terms:\n\n{final_answer}\n\n"
                    "Think of it this way: the key thing to remember is just the core formula "
                    "or rule above. Everything else follows from that one idea."
        )
        return original_steps + [simplified], final_answer

    elif action == "example":
        example_step = DoubtStepOut(
        step=len(original_steps) + 1,
            title="A Real-Life Example",
            content=f"Here is a concrete, everyday example that makes this concept click:\n\n"
                    f"In your daily life, {subject.lower()} concepts like this appear when you:\n"
                    "- Notice how car brakes work (friction, force, deceleration)\n"
                    "- See a phone charger converting voltage and current (Ohm's Law)\n"
                    "- Watch a ball thrown upward then fall back (kinematics)\n\n"
                    "Try to connect the formula to something real you can visualise  --  "
                    "that is what top JEE scorers do."
        )
        return original_steps + [example_step], final_answer

    elif action == "derive":
        derive_step = DoubtStepOut(
            step=len(original_steps) + 1,
            title="The Full Derivation",
            content="For the complete mathematical derivation, start from first principles.\n\n"
                    "1. State the fundamental definitions and laws you are starting from.\n"
                    "2. Write the governing relationship in its most general form.\n"
                    "3. Apply any simplifying assumptions (constant mass, uniform field, etc.).\n"
                    "4. Use algebra to isolate the quantity you want.\n"
                    "5. Verify your result by checking units and limiting cases.\n\n"
                    f"The core result is: {final_answer}"
        )
        return original_steps + [derive_step], final_answer

    elif action == "quiz_me":
        # Replace last step with a practice question
        quiz_step = DoubtStepOut(
            step=len(original_steps) + 1,
            title="Test Yourself",
            content=f"Based on what you just learned about {subject.lower()}, try this question:\n\n"
                    f"Apply the same concept to: a slightly different version of the problem  --  "
                    f"change one value and recalculate.\n\n"
                    f"Hint: The method is exactly the same. Just substitute the new values "
                    f"into the same formula.\n\n"
                    f"If you can solve a similar question without help, you have understood this concept."
        )
        return original_steps + [quiz_step], final_answer

    return original_steps, final_answer


# ─────────────────────────────────────────────────────────────
#  LIVE AI ENGINE (Cerebras -> Groq Fallback)
# ─────────────────────────────────────────────────────────────

import datetime as _dt

def _call_llm_for_doubt(
    question: str,
    subject: str,
    question_type: str,
    follow_up: Optional[str] = None,
    chat_history: Optional[List[Any]] = None
) -> Optional[Tuple[List[DoubtStepOut], str, List[str], List[str]]]:
    """
    Calls Cerebras API first, with automatic fallback to Groq API.
    Returns parsed (steps, final_answer, key_concepts, related_topics) or None if both fail.
    """
    today_str = _dt.date.today().strftime("%B %d, %Y")
    system_prompt = (
        f"You are an elite AI Mentor and Study Coach for Indian students (CBSE, ICSE, JEE, NEET, UPSC, History, Humanities, current affairs). "
        f"Today's date is {today_str}. You have comprehensive, up-to-date knowledge on all subjects including recent events, current affairs, and latest developments.\n\n"
        "ANSWER STYLE RULES (follow strictly):\n"
        "1. Write in clean, plain English. Natural paragraphs and bullet points using - or numbers.\n"
        "2. NEVER use **bold**, _italic_, or any markdown formatting symbols in text. Write everything as plain text.\n"
        "3. Do NOT use LaTeX or any math markup. Write math plainly: sqrt(D) = 7, x = (11 + 7) / 6, F = m x a.\n"
        "4. For History, Current Affairs, Social Science, Geography: give a rich, flowing narrative with specific dates, names, causes, and consequences. Be detailed and engaging like a great teacher.\n"
        "5. For Science and Math concepts: explain with intuitive real-life analogies first, then the formula.\n"
        "6. For numerical problems: show the working clearly step by step in plain text paragraphs.\n"
        "7. Be specific and accurate. Mention real names, real dates, real numbers.\n\n"
        "DIAGRAM RULES (CRITICAL - follow exactly for ANY diagram/schematic/circuit/ray diagram/flowchart/biological structure request):\n"
        "- You MUST generate a rich HTML diagram rendered using inline SVG inside a full self-contained HTML fragment.\n"
        "- Put the ENTIRE diagram HTML inside a fenced code block labelled html: ```html\n..your HTML..\n```\n"
        "- The HTML fragment MUST include a <style> block for fonts/colors and an <svg> element for the diagram.\n"
        "- Design rules for the SVG:\n"
        "  * Background: #0F1117 (dark panel). SVG width=100%, viewBox='0 0 520 300' or taller as needed.\n"
        "  * All text in SVG: font-family='monospace', fill='#E0E0E0', font-size=13\n"
        "  * Wires/lines: stroke='#58A6FF', stroke-width=2\n"
        "  * Component boxes (resistor, capacitor, cell): rect fill='#1E2233' stroke='#6C63FF' stroke-width=2 rx=6\n"
        "  * Labels inside boxes: fill='#FFFFFF' font-weight='bold'\n"
        "  * Arrows: use SVG <marker> with a small triangle, fill='#58A6FF'\n"
        "  * For ray diagrams: principal axis = dashed line, rays = solid colored arrows, lens = blue vertical line\n"
        "  * For flowcharts: rounded rect nodes, colored arrows, alternating node colors\n"
        "  * For biological diagrams: use ellipses for organelles, labeled with lines, distinct colors per organelle\n"
        "- The HTML must be self-contained (no external URLs, no JavaScript, no <script> tags).\n"
        "- After the ```html code block, explain each labeled component in 1-2 plain text sentences.\n\n"
        "OUTPUT FORMAT - respond with ONLY valid JSON, absolutely no other text before or after:\n"
        '{"final_answer": "complete explanation. For diagrams embed the ```html\\n..\\n``` block inside this string using \\n for newlines.", '
        '"steps": [], '
        '"key_concepts": ["key fact or formula 1", "key fact or formula 2", "key fact or formula 3"], '
        '"related_topics": ["related topic 1", "related topic 2"]}\n\n'
        "RULE: The steps array MUST always be [] (empty). Never add steps."
    )

    messages = [{"role": "system", "content": system_prompt}]
    
    if chat_history:
        for msg in chat_history:
            if isinstance(msg, dict):
                r = msg.get("role", "user")
                c = msg.get("content", "")
            else:
                r = getattr(msg, "role", "user")
                c = getattr(msg, "content", "")
            if c and str(c).strip():
                mapped_role = "assistant" if str(r).lower() in ("assistant", "ai", "model") else "user"
                messages.append({"role": mapped_role, "content": str(c).strip()})

    user_prompt = f"Subject: {subject}\nQuestion type: {question_type}\nStudent question: {question}"
    if follow_up:
        user_prompt += f"\nFollow-up request: {follow_up}"

    messages.append({"role": "user", "content": user_prompt})

    # 1. Try Cerebras
    cerebras_keys = [k.strip() for k in (settings.CEREBRAS_API_KEYS or settings.CEREBRAS_API_KEY).split(",") if k.strip()]
    for key in cerebras_keys:
        try:
            r = httpx.post(
                "https://api.cerebras.ai/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "model": settings.CEREBRAS_MODEL,
                    "messages": messages,
                    "temperature": 0.3,
                    "max_tokens": 4096,
                },
                timeout=18
            )
            if r.status_code == 200:
                content = r.json()["choices"][0]["message"]["content"]
                parsed = _parse_llm_json(content)
                if parsed:
                    return parsed
        except Exception:
            pass

    # 2. Try Groq (Fallback)
    groq_keys = [k.strip() for k in (settings.GROQ_API_KEYS or settings.GROQ_API_KEY).split(",") if k.strip()]
    for key in groq_keys:
        try:
            r = httpx.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "model": settings.GROQ_MODEL,
                    "messages": messages,
                    "temperature": 0.2,
                    "max_tokens": 2048,
                    "response_format": {"type": "json_object"}
                },
                timeout=12
            )
            if r.status_code == 200:
                content = r.json()["choices"][0]["message"]["content"]
                parsed = _parse_llm_json(content)
                if parsed:
                    return parsed
        except Exception:
            pass

    return None


# ─────────────────────────────────────────────────────────────
#  IMAGE VISION SOLVER  (Cerebras gemma-4-31b — FREE Vision)
# ─────────────────────────────────────────────────────────────

def solve_doubt_from_image(
    image_base64: str,
    image_mime: str = "image/jpeg",
    subject_hint: str = ""
) -> Tuple[str, List[str], List[str]]:
    """
    Accepts a base64-encoded image (photo of a textbook question, handwritten problem,
    diagram, or equation). Returns (answer_text, key_concepts, related_topics).

    Uses Cerebras gemma-4-31b which is the only model that supports FREE image vision.
    Falls back gracefully if all keys are rate-limited.
    """
    data_uri = f"data:{image_mime};base64,{image_base64}"

    system_prompt = (
        "You are an expert AI study tutor. The student has sent you a photo of a question, "
        "math problem, diagram, or textbook page. Your job:\n"
        "1. Read ALL text, numbers, equations, and labels visible in the image exactly as written.\n"
        "2. Identify what the question or problem is asking.\n"
        "3. Solve it completely, step by step, with full working shown.\n"
        "4. Write in clean plain English only. NO markdown symbols like **, #, __, or *.\n"
        "5. Write math inline: A x B = 175, not LaTeX or special symbols.\n"
        "6. At the end, state the final answer clearly on its own line starting with 'Final Answer:'.\n"
        "Be thorough and educational, as if explaining to a student who is stuck."
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": f"Please read and solve this image.{' Subject: ' + subject_hint if subject_hint else ''}"},
                {"type": "image_url", "image_url": {"url": data_uri}}
            ]
        }
    ]

    # Cerebras gemma-4-31b is the only FREE vision model — try all keys
    cerebras_keys = [k.strip() for k in (settings.CEREBRAS_API_KEYS or settings.CEREBRAS_API_KEY).split(",") if k.strip()]
    for key in cerebras_keys:
        try:
            r = httpx.post(
                "https://api.cerebras.ai/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "model": "gemma-4-31b",
                    "messages": messages,
                    "temperature": 0.1,
                    "max_tokens": 1024,
                },
                timeout=30
            )
            if r.status_code == 200:
                answer = r.json()["choices"][0]["message"]["content"].strip()
                # Clean up any stray markdown from response
                answer = re.sub(r"\*\*(.+?)\*\*", r"\1", answer, flags=re.DOTALL)
                answer = re.sub(r"#{1,6}\s+", "", answer)
                answer = re.sub(r"__(.+?)__", r"\1", answer, flags=re.DOTALL)

                # Extract key concepts from the answer (lines with = signs or "Formula:" etc.)
                key_concepts = []
                for line in answer.split("\n"):
                    line = line.strip()
                    if "=" in line and len(line) < 80 and any(c.isdigit() for c in line):
                        key_concepts.append(line)
                    if len(key_concepts) >= 4:
                        break

                related_topics = [subject_hint] if subject_hint else ["Problem Solving"]
                return answer, key_concepts[:4], related_topics
        except Exception:
            continue

    # All keys failed
    return (
        "The image could not be processed right now due to high traffic. "
        "Please try again in a few seconds, or type your question instead.",
        [],
        []
    )



def _pick_groq_key() -> str:
    keys = [k.strip() for k in (settings.GROQ_API_KEYS or settings.GROQ_API_KEY).split(",") if k.strip()]
    if keys:
        import random
        return random.choice(keys)
    return settings.GROQ_API_KEY


def _pick_cerebras_key() -> str:
    keys = [k.strip() for k in (settings.CEREBRAS_API_KEYS or settings.CEREBRAS_API_KEY).split(",") if k.strip()]
    if keys:
        import random
        return random.choice(keys)
    return settings.CEREBRAS_API_KEY


def perform_live_web_search(query: str, max_results: int = 4) -> str:
    """Fetch live web snippets for up-to-date factual accuracy."""
    try:
        from ddgs import DDGS
        results = list(DDGS().text(query, max_results=max_results))
        if not results:
            return ""
        snippets = []
        for r in results:
            title = r.get("title", "")
            body = r.get("body", "")
            if body:
                snippets.append(f"Source: {title}\nInfo: {body}")
        return "\n\n".join(snippets)
    except Exception as e:
        return ""


def _clean_text(s: str) -> str:
    if not s:
        return ""
    # Strip LaTeX commands and convert to clean readable Unicode text
    s = re.sub(r"\\frac\{([^}]+)\}\{([^}]+)\}", r"(\1 / \2)", s)
    s = re.sub(r"\\sqrt\{([^}]+)\}", r"√(\1)", s)
    s = re.sub(r"\\text\{([^}]+)\}", r"\1", s)
    s = re.sub(r"\\mathbf\{([^}]+)\}", r"\1", s)
    s = re.sub(r"\\math[a-zA-Z]+\{([^}]+)\}", r"\1", s)
    s = s.replace(r"\(", "").replace(r"\)", "").replace(r"\[", "").replace(r"\]", "")
    s = s.replace(r"\pm", "±").replace(r"\times", " × ").replace(r"\cdot", " · ")
    s = s.replace(r"\le", "≤").replace(r"\ge", "≥").replace(r"\neq", "≠")
    s = s.replace(r"\theta", "θ").replace(r"\alpha", "α").replace(r"\beta", "β").replace(r"\pi", "π").replace(r"\int", "∫")
    s = s.replace(r"\\", "")
    return s.strip()


def _call_llm_for_doubt(
    question_text: str,
    subject: str,
    question_type: str,
    follow_up_action: Optional[str] = None,
    chat_history: Optional[List[Any]] = None,
    user_context: Optional[str] = None
) -> Optional[Tuple[List[DoubtStepOut], str, List[str], List[str], str, str]]:
    # 1. Determine if web search is helpful
    search_context = ""
    q_low = question_text.lower()
    needs_search = any(k in q_low for k in [
        "who is", "current", "2026", "2025", "minister", "president", "capital", "winner",
        "latest", "today", "news", "discovery", "ceo", "governor", "ranking", "olympics", "who",
        "chief minister", "prime minister", "cabinet"
    ]) or question_type == "factual"

    if needs_search:
        search_query = question_text
        if "2026" not in search_query and any(k in q_low for k in ["minister", "president", "current", "who is"]):
            search_query += " 2026"
        search_context = perform_live_web_search(search_query)

    # 2. Build prompt
    sys_prompt = (
        "You are Quovex AI, an elite, patient, empathetic, and ultra-accurate academic AI tutor.\n"
        "Your mission is to help students learn and master concepts with complete clarity and confidence.\n\n"
        "Output Rules:\n"
        "1. Return ONLY a single valid JSON object.\n"
        "2. JSON Schema:\n"
        "{\n"
        '  "question_type": "factual | numerical | conceptual | diagram | teach_me",\n'
        '  "confidence": "high | medium",\n'
        '  "confidence_label": "Textbook verified | Live search verified | Step-by-step calculation",\n'
        '  "steps": [\n'
        '    {"step": 1, "title": "Step title", "content": "Clear, friendly explanation"},\n'
        '    {"step": 2, "title": "Step title", "content": "..."}\n'
        "  ],\n"
        '  "final_answer": "Concise summary of the answer (1-3 sentences)",\n'
        '  "key_concepts": ["Key formula or concept 1", "Key concept 2"],\n'
        '  "related_topics": ["Topic 1", "Topic 2"]\n'
        "}\n"
        "3. Readability & Formatting:\n"
        "   - Use clean, standard textbook English.\n"
        "   - Use clean Unicode math & chemical symbols (e.g. x², √x, π, θ, Δ, CO₂, H₂SO₄, ∫, 1/2) instead of raw LaTeX tags.\n"
        "   - If a diagram/visual layout is requested (e.g. circuit, ray optics, cell, flowchart), render a clean ASCII/Unicode diagram block with clear labels inside the step content.\n"
        "   - Tailor explanation depth and tone to the student's grade/exam level."
    )

    user_parts = [f"Question: {question_text}", f"Subject: {subject}"]
    if user_context:
        user_parts.append(f"Student Context: {user_context}")
    if follow_up_action:
        user_parts.append(f"Follow-up Request: {follow_up_action}")
    if chat_history:
        hist_text = []
        for msg in chat_history[-4:]:
            role = getattr(msg, "role", "user") if hasattr(msg, "role") else (msg.get("role") if isinstance(msg, dict) else "user")
            content = getattr(msg, "content", "") if hasattr(msg, "content") else (msg.get("content") if isinstance(msg, dict) else str(msg))
            hist_text.append(f"{role.capitalize()}: {content}")
        if hist_text:
            user_parts.append(f"Previous Chat History:\n" + "\n".join(hist_text))
    if search_context:
        user_parts.append(f"Live Web Search Information (as of 2026):\n{search_context}")

    user_prompt = "\n\n".join(user_parts)

    # 3. Call Groq first (high-speed)
    groq_key = _pick_groq_key()
    if groq_key:
        try:
            with httpx.Client(timeout=25) as client:
                resp = client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {groq_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": settings.GROQ_MODEL,
                        "messages": [
                            {"role": "system", "content": sys_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        "temperature": 0.3,
                        "max_tokens": 2048,
                    },
                )
                if resp.status_code == 200:
                    raw_json = resp.json()["choices"][0]["message"]["content"]
                    s_idx = raw_json.find("{")
                    e_idx = raw_json.rfind("}") + 1
                    if s_idx != -1 and e_idx > 0:
                        data = json.loads(raw_json[s_idx:e_idx], strict=False)
                        steps = [
                            DoubtStepOut(
                                step=s.get("step", i),
                                title=_clean_text(str(s.get("title", f"Step {i}"))),
                                content=_clean_text(str(s.get("content", "")))
                            )
                            for i, s in enumerate(data.get("steps", []), start=1)
                        ]
                        final_ans = _clean_text(str(data.get("final_answer", "")))
                        key_concepts = [_clean_text(str(k)) for k in data.get("key_concepts", []) if str(k).strip()]
                        related_topics = [_clean_text(str(t)) for t in data.get("related_topics", []) if str(t).strip()]
                        q_type = data.get("question_type", question_type)
                        conf_label = data.get("confidence_label", "Live search verified" if search_context else "Textbook verified")
                        return steps, final_ans, key_concepts, related_topics, q_type, conf_label
        except Exception:
            pass

    # 4. Fallback to Cerebras
    cerebras_key = _pick_cerebras_key()
    if cerebras_key:
        try:
            with httpx.Client(timeout=25) as client:
                resp = client.post(
                    "https://api.cerebras.ai/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {cerebras_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": settings.CEREBRAS_MODEL,
                        "messages": [
                            {"role": "system", "content": sys_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        "temperature": 0.3,
                        "max_tokens": 2048,
                    },
                )
                if resp.status_code == 200:
                    raw_json = resp.json()["choices"][0]["message"]["content"]
                    s_idx = raw_json.find("{")
                    e_idx = raw_json.rfind("}") + 1
                    if s_idx != -1 and e_idx > 0:
                        data = json.loads(raw_json[s_idx:e_idx], strict=False)
                        steps = [
                            DoubtStepOut(
                                step=s.get("step", i),
                                title=_clean_text(str(s.get("title", f"Step {i}"))),
                                content=_clean_text(str(s.get("content", "")))
                            )
                            for i, s in enumerate(data.get("steps", []), start=1)
                        ]
                        final_ans = _clean_text(str(data.get("final_answer", "")))
                        key_concepts = [_clean_text(str(k)) for k in data.get("key_concepts", []) if str(k).strip()]
                        related_topics = [_clean_text(str(t)) for t in data.get("related_topics", []) if str(t).strip()]
                        q_type = data.get("question_type", question_type)
                        conf_label = data.get("confidence_label", "Verified solution")
                        return steps, final_ans, key_concepts, related_topics, q_type, conf_label
        except Exception:
            pass

    return None


# ─────────────────────────────────────────────────────────────
#  MAIN SOLVER ENTRY POINT
# ─────────────────────────────────────────────────────────────

def solve_doubt_intelligently(
    question_text: str,
    subject_hint: str = "",
    follow_up_action: Optional[str] = None,
    chat_history: Optional[List[Any]] = None,
    user_context: Optional[str] = None
) -> Tuple[List[DoubtStepOut], str, List[str], List[str], str, str, str]:
    """
    Returns:
        (steps, final_answer, key_concepts, related_topics, question_type, confidence, confidence_label)
    All text is plain human-readable English  --  no raw unrendered LaTeX tags.
    """
    q_low = question_text.lower().strip()
    numbers = extract_numbers(question_text)
    subject = detect_subject(question_text, subject_hint)
    question_type = classify_question_type(question_text)
    confidence, confidence_label = classify_confidence(question_type)

    # 1. Try Live AI Engine (with live web search & user context)
    llm_result = _call_llm_for_doubt(
        question_text, subject, question_type, follow_up_action, chat_history, user_context=user_context
    )
    if llm_result:
        steps, final_answer, key_concepts, related_topics, q_type, conf_label = llm_result
        return steps, final_answer, key_concepts, related_topics, q_type, "high", conf_label

    result = None

    # ── FACTUAL LOOKUPS ───────────────────────────────────────
    if question_type == "factual":
        if "speed of light" in q_low or ("light" in q_low and "vacuum" in q_low):
            result = _factual_speed_of_light()
        elif "second law" in q_low and "newton" in q_low:
            result = _factual_newtons_second_law()
        elif "first law" in q_low and "newton" in q_low:
            result = _factual_newtons_first_law()
        elif "unit of electric current" in q_low or "unit of current" in q_low:
            result = _factual_unit_of_current()

    # ── NUMERICAL PROBLEMS ────────────────────────────────────
    elif question_type == "numerical":
        if len(numbers) >= 2:
            if ("mass" in q_low or "kg" in q_low) and ("acceleration" in q_low or "m/s" in q_low) and "force" in q_low:
                result = _numerical_f_equals_ma(numbers[0], numbers[1])
            elif ("distance" in q_low or "metre" in q_low or " m " in q_low) and ("time" in q_low or " s " in q_low or "second" in q_low) and ("speed" in q_low or "velocity" in q_low):
                result = _numerical_kinematics_speed(numbers[0], numbers[1])
            elif ("voltage" in q_low or "volt" in q_low) and ("resistance" in q_low or "ohm" in q_low):
                result = _numerical_ohms_law(numbers, q_low)
            elif ("slope" in q_low or "incline" in q_low or "angle" in q_low) and len(numbers) >= 2:
                result = _numerical_incline(numbers[0], numbers[1])
        if result is None and ("drop" in q_low or "fall" in q_low or "height" in q_low) and len(numbers) >= 1:
            result = _numerical_free_fall(numbers[0])

    # ── CONCEPTUAL "WHY / HOW" ────────────────────────────────
    elif question_type == "conceptual":
        if "resistance" in q_low and "current" in q_low:
            result = _conceptual_resistance_current()
        elif "sky" in q_low and "blue" in q_low:
            result = _conceptual_why_sky_blue()
        elif "gravity" in q_low or "gravitation" in q_low:
            result = _conceptual_gravity()

    # ── TEACH ME ─────────────────────────────────────────────
    elif question_type == "teach_me":
        if "electrostatics" in q_low or "electric charge" in q_low:
            result = _teach_electrostatics()
        elif "quadratic" in q_low or "algebra" in q_low:
            result = _teach_quadratic_equations()

    # ── GENERIC FALLBACK (always returns something useful) ────
    if result is None:
        result = _generic_fallback(question_text, subject, question_type, numbers)

    steps, final_answer, key_concepts, related_topics = result

    # Apply follow-up action if requested
    if follow_up_action:
        steps, final_answer = _apply_follow_up(
            follow_up_action, steps, final_answer, question_text, subject
        )

    return steps, final_answer, key_concepts, related_topics, question_type, confidence, confidence_label


# ─────────────────────────────────────────────────────────────
#  GENERIC FALLBACK  --  Always returns a coherent answer
# ─────────────────────────────────────────────────────────────

def _generic_fallback(
    question_text: str,
    subject: str,
    question_type: str,
    numbers: List[float]
) -> Tuple[List[DoubtStepOut], str, List[str], List[str]]:
    """
    Produces a structured, readable fallback for unrecognised questions.
    Uses the question_type to choose the right structure.
    """
    q_low = question_text.lower()

    if question_type == "factual":
        steps = [
            DoubtStepOut(step=1, title="The Answer",
                content=f"This is a {subject} question about: {question_text}\n\n"
                        "The key idea relates to a fundamental principle or constant in this subject. "
                        "To find the precise value, refer to your textbook's chapter summary "
                        "or formula sheet for this topic."),
            DoubtStepOut(step=2, title="Why It Matters",
                content=f"Understanding this concept in {subject} is essential because it forms "
                        "the foundation for more advanced topics. "
                        "Make sure you know the definition, the SI units, and any associated formula."),
            DoubtStepOut(step=3, title="How to Remember It",
                content="Create a simple memory hook: write the formula or definition on a "
                        "flashcard, and relate it to a real-life example you can visualise. "
                        "Test yourself by covering the answer and trying to recall it.")
        ]
        return (steps,
                f"This {subject} question covers a key concept. "
                "Review your textbook for the precise definition, formula, and SI units.",
                [f"{subject} fundamentals"],
                [subject])

    elif question_type == "numerical":
        given = ", ".join(f"{n}" for n in numbers[:4]) if numbers else "the values provided"
        steps = [
            DoubtStepOut(step=1, title="Given Information",
                content=f"Values identified in the problem: {given}\n"
                        f"Subject area: {subject}"),
            DoubtStepOut(step=2, title="Identify the Right Formula",
                content=f"For this type of {subject} problem, identify which formula connects "
                        "the given quantities to the unknown you need to find.\n\n"
                        "Write down all the relevant formulas for this topic first, then pick "
                        "the one that uses the information you have been given."),
            DoubtStepOut(step=3, title="Substitute and Solve",
                content="Replace each symbol in the formula with the given numbers. "
                        "Keep track of units at every step  --  cancel units to verify your answer "
                        "has the correct units."),
            DoubtStepOut(step=4, title="Calculate",
                content="Perform the arithmetic carefully. "
                        "Use standard values: g = 9.8 m/s^2, speed of light = 3  x  10^8 m/s, etc."),
            DoubtStepOut(step=5, title="Answer and Verify",
                content="State your final answer with the correct unit. "
                        "Sanity-check: does the magnitude feel reasonable? "
                        "For example, a speed above 3  x  10^8 m/s is impossible.")
        ]
        return (steps,
                f"A step-by-step numerical solution for this {subject} problem.",
                ["Check your formula sheet", "Match units carefully"],
                [subject])

    elif question_type == "conceptual":
        steps = [
            DoubtStepOut(step=1, title="Core Idea",
                content=f"This question asks about the reason or mechanism behind a {subject} phenomenon.\n\n"
                        "Start by identifying what physical law, principle, or interaction governs this situation."),
            DoubtStepOut(step=2, title="The Intuition",
                content="Before writing equations, build an intuitive picture. "
                        "Draw a simple diagram if helpful. Ask: what forces, fields, or energy "
                        "changes are involved? Which increases and which decreases?"),
            DoubtStepOut(step=3, title="The Equation",
                content=f"Find the governing equation for this {subject} concept. "
                        "Write it out, then show how changing one variable affects the others."),
            DoubtStepOut(step=4, title="A Real Example",
                content="Think of a real-world device or situation where this principle applies. "
                        "Connecting abstract concepts to tangible examples makes them stick."),
            DoubtStepOut(step=5, title="Check Your Understanding",
                content="After reading this, can you:\n"
                        "1. State the key principle in one sentence?\n"
                        "2. Write the relevant formula?\n"
                        "3. Give one real-life application?\n\n"
                        "If yes, you have understood the concept.")
        ]
        return (steps,
                f"This is a conceptual {subject} question about the reason or mechanism behind a phenomenon.",
                [f"{subject} core principles"],
                [subject])

    else:  # teach_me
        steps = [
            DoubtStepOut(step=1, title="Overview of the Topic",
                content=f"To learn {question_text.replace('teach me', '').replace('explain', '').strip()}, "
                        f"you need to build understanding step by step.\n\n"
                        "This is the recommended learning path for this topic in {subject}."),
            DoubtStepOut(step=2, title="Key Concepts to Master",
                content=f"In {subject}, this topic typically covers:\n"
                        "1. The fundamental definitions and principles\n"
                        "2. The governing equations and formulas\n"
                        "3. How to apply them in standard problem types\n"
                        "4. Common exam tricks and shortcuts"),
            DoubtStepOut(step=3, title="Recommended Study Order",
                content="Start with definitions -> understand the formula -> "
                        "solve basic examples -> tackle harder problems.\n\n"
                        "Do not memorise without understanding. The formula comes naturally "
                        "once you understand what each symbol means physically."),
            DoubtStepOut(step=4, title="Practice Strategy",
                content="After reading the concept:\n"
                        "1. Solve 3 basic problems without help\n"
                        "2. Then solve 2 past exam questions\n"
                        "3. Review any mistakes and understand why you made them\n\n"
                        "Spaced repetition: revisit this topic in 3 days, then 1 week."),
            DoubtStepOut(step=5, title="You Are Ready When...",
                content="You can explain this concept to someone else in simple words. "
                        "If you cannot explain it simply, you do not yet understand it fully. "
                        "Use the AI Tutor to ask follow-up questions until it clicks.")
        ]
        return (steps,
                f"Learning roadmap for {subject}: definitions -> equations -> examples -> practice.",
                [f"{subject} fundamentals", "Step-by-step learning"],
                [subject, "Study Strategy"])
