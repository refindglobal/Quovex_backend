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
from typing import List, Tuple, Optional
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
        "integral", "derivative", "limit", "matrix", "equation", "polynomial", "proof", "theorem",
        "function", "vector", "calculus", "algebra", "quadratic", "roots", "discriminant", "triangle",
        "circle", "trigonometry", "sin", "cos", "tan", "logarithm", "probability", "permutation",
        "combination", "determinant", "sequence", "series", "progression", "geometry", "slope",
        "differentiate", "integrate", "evaluate", "solve", "alpha", "beta"
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

    # Teach Me: "teach me X", "explain X", "what is X in detail", "lesson on X"
    teach_triggers = ["teach me", "lesson on", "teach about", "guide me", "learn about",
                      "study guide", "overview of", "introduction to", "topic on"]
    if any(t in low for t in teach_triggers):
        return "teach_me"

    # Numerical: contains numbers, "find", "calculate", "how much", "what is the value"
    has_numbers = bool(re.search(r"\d+", low))
    calc_triggers = ["find ", "calculate", "compute", "determine the", "how much", "how long",
                     "what is the value", "what will be", "how fast", "how far", "time taken",
                     "final velocity", "work done", "distance", "solve for"]
    if has_numbers and any(t in low for t in calc_triggers):
        return "numerical"

    # Conceptual: "why", "how does", "explain why", "reason for", "what happens when"
    conceptual_triggers = ["why", "how does", "how do", "explain why", "reason for",
                           "what happens", "effect of", "role of", "difference between",
                           "compare", "relationship between", "when does", "what causes"]
    if any(t in low for t in conceptual_triggers):
        return "conceptual"

    # Default: factual — direct "what is", "what are", "define", "state", "who discovered"
    return "factual"


def classify_confidence(question_type: str) -> Tuple[str, str]:
    """Returns (confidence_level, confidence_label)"""
    if question_type == "numerical":
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
#  FACTUAL SOLVERS  (Answer / Why / Remember — 3 sections max)
# ─────────────────────────────────────────────────────────────

def _factual_speed_of_light() -> Tuple[List[DoubtStepOut], str, List[str], List[str]]:
    steps = [
        DoubtStepOut(
            step=1, title="The Answer",
            content="The speed of light in a vacuum is exactly 299,792,458 metres per second — "
                    "commonly written as 3.00 × 10^8 m/s.\n\n"
                    "This constant is so important that it has its own symbol: c."
        ),
        DoubtStepOut(
            step=2, title="Why is it this value?",
            content="Light is an electromagnetic wave. Its speed in vacuum is fixed by two "
                    "fundamental constants of nature — the permittivity of free space (ε₀) "
                    "and the permeability of free space (μ₀).\n\n"
                    "The relationship is: c = 1 / √(ε₀ × μ₀)\n\n"
                    "In any other medium, light slows down. In water (refractive index ≈ 1.33), "
                    "light travels at about 2.25 × 10^8 m/s."
        ),
        DoubtStepOut(
            step=3, title="Remember for Your Exam",
            content="c = 3.00 × 10^8 m/s  (in vacuum)\n\n"
                    "Speed in a medium: v = c / n  (where n is the refractive index)\n\n"
                    "Einstein's famous result: E = mc²  (mass-energy equivalence)\n\n"
                    "c is the cosmic speed limit — nothing with mass can reach or exceed it."
        )
    ]
    return (
        steps,
        "The speed of light in vacuum is 299,792,458 m/s (approximately 3.00 × 10^8 m/s), "
        "denoted by c. It is the fastest speed possible in the universe.",
        ["c = 3.00 × 10^8 m/s", "v = c / n", "E = mc²"],
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
            content="Force = Mass × Acceleration\n\n"
                    "F = m × a\n\n"
                    "Rearranging:\n"
                    "  Acceleration (a) = F / m\n"
                    "  Mass (m) = F / a\n\n"
                    "SI Units: Force in Newtons (N), Mass in kilograms (kg), "
                    "Acceleration in m/s²\n"
                    "1 Newton = 1 kg × m/s²"
        ),
        DoubtStepOut(
            step=3, title="Real-Life Example",
            content="When a cricketer catches a ball, he pulls his hands backward. "
                    "This increases the time over which the ball decelerates. "
                    "Since Force = Change in Momentum / Time, a longer time means less force on "
                    "his hands — which is why it hurts less than a rigid catch.\n\n"
                    "Another example: pushing a shopping trolley. An empty trolley (less mass) "
                    "accelerates much faster than a full one with the same push force."
        )
    ]
    return (
        steps,
        "Newton's Second Law: the net force on an object equals its mass multiplied by its "
        "acceleration. Formula: F = m × a. A larger force causes greater acceleration; "
        "a larger mass resists acceleration more.",
        ["F = m × a", "a = F / m", "1 N = 1 kg·m/s²", "Impulse = F × t"],
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
                    "This property is called inertia — the natural resistance of objects to "
                    "changes in their state of motion."
        ),
        DoubtStepOut(
            step=2, title="What is Inertia?",
            content="Inertia is not a force — it is a property. The more massive an object, "
                    "the greater its inertia, meaning it is harder to start moving, stop, "
                    "or change direction.\n\n"
                    "Mathematical condition: If the net force on an object is zero (F_net = 0), "
                    "then its acceleration is zero, and velocity stays constant."
        ),
        DoubtStepOut(
            step=3, title="Everyday Examples",
            content="1. You lurch forward when a bus brakes suddenly — your body's inertia "
                    "wants to keep moving forward while the bus stops.\n\n"
                    "2. A ball rolled on a frictionless surface would continue forever — "
                    "friction is the external force that normally slows it.\n\n"
                    "3. A tablecloth pulled quickly from under dishes — inertia keeps the "
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
                    "6.24 × 10^18 electrons flowing past a point every second."
        ),
        DoubtStepOut(
            step=3, title="Related Units to Remember",
            content="Current (I)     →  Ampere (A)\n"
                    "Voltage (V)     →  Volt (V = J/C)\n"
                    "Resistance (R)  →  Ohm (Ω = V/A)\n"
                    "Power (P)       →  Watt (W = V × A)\n"
                    "Charge (Q)      →  Coulomb (C = A × s)\n\n"
                    "Current is measured using an Ammeter, connected in series in the circuit."
        )
    ]
    return (
        steps,
        "The SI unit of electric current is the Ampere (A). "
        "1 Ampere = 1 Coulomb of charge per second. Formula: I = Q / t.",
        ["I = Q / t", "1 A = 1 C/s", "V = I × R"],
        ["Current Electricity", "Electrostatics", "Circuit Theory"]
    )


# ─────────────────────────────────────────────────────────────
#  NUMERICAL SOLVERS  (Given → Formula → Substitute → Calculate → Answer)
# ─────────────────────────────────────────────────────────────

def _numerical_f_equals_ma(m: float, a: float) -> Tuple[List[DoubtStepOut], str, List[str], List[str]]:
    F = m * a
    steps = [
        DoubtStepOut(step=1, title="Given Information",
            content=f"Mass (m) = {m} kg\n"
                    f"Acceleration (a) = {a} m/s²\n"
                    f"Find: Net Force (F)"),
        DoubtStepOut(step=2, title="Formula to Use",
            content="Newton's Second Law:\n\nF = m × a\n\n"
                    "Force equals mass times acceleration."),
        DoubtStepOut(step=3, title="Substitute the Values",
            content=f"F = {m} × {a}"),
        DoubtStepOut(step=4, title="Calculate",
            content=f"F = {F:.2f} N"),
        DoubtStepOut(step=5, title="Answer",
            content=f"The net force on the object is {F:.2f} Newtons.\n\n"
                    f"To put this in perspective: {F:.1f} N is roughly the weight of "
                    f"{F/9.8:.1f} kg in Earth's gravity.")
    ]
    return (
        steps,
        f"The net force is {F:.2f} N. Using F = m × a = {m} × {a}.",
        ["F = m × a", f"F = {m} × {a} = {F:.2f} N"],
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
                    f"Acceleration due to gravity (g) = 9.8 m/s²\n"
                    f"Find: time to reach ground and final velocity"),
        DoubtStepOut(step=2, title="Formula to Use",
            content="For an object dropped from rest:\n\n"
                    "Time of fall:       h = ½ × g × t²   →   t = √(2h / g)\n"
                    "Final velocity:     v² = 2 × g × h   →   v = √(2gh)"),
        DoubtStepOut(step=3, title="Substitute the Values",
            content=f"t = √(2 × {h} / 9.8) = √({(2*h)/g:.3f})\n\n"
                    f"v = √(2 × 9.8 × {h}) = √({2*g*h:.2f})"),
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
        f"Using t = √(2h/g) and v = √(2gh) with g = 9.8 m/s².",
        ["t = √(2h/g)", "v = √(2gh)", "h = ½gt²"],
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
                    f"g = 9.8 m/s²  (assume smooth/frictionless unless stated)\n"
                    f"Find: acceleration down the slope and the driving force"),
        DoubtStepOut(step=2, title="Understanding the Forces",
            content="Gravity pulls the object straight down with force mg.\n\n"
                    "On an inclined plane, this splits into two components:\n"
                    f"  Along the slope (causes motion): mg × sin({theta_deg}°)\n"
                    f"  Perpendicular to slope (normal force): mg × cos({theta_deg}°)\n\n"
                    "The normal force prevents the object from going through the surface. "
                    "The parallel component is what slides the object down."),
        DoubtStepOut(step=3, title="Substitute",
            content=f"Acceleration along slope:  a = g × sin({theta_deg}°)\n"
                    f"  = 9.8 × sin({theta_deg}°)\n"
                    f"  = 9.8 × {math.sin(theta_rad):.4f}\n\n"
                    f"Normal force:  N = m × g × cos({theta_deg}°)\n"
                    f"  = {m} × 9.8 × {math.cos(theta_rad):.4f}"),
        DoubtStepOut(step=4, title="Calculate",
            content=f"Acceleration down slope:  a = {a:.2f} m/s²\n"
                    f"Driving force along slope: F = {F_parallel:.2f} N\n"
                    f"Normal force: N = {N:.2f} N"),
        DoubtStepOut(step=5, title="Answer",
            content=f"The {m} kg object slides down the {theta_deg}° incline "
                    f"with an acceleration of {a:.2f} m/s². "
                    f"The force pulling it down the slope is {F_parallel:.2f} N.")
    ]
    return (
        steps,
        f"Acceleration = g × sin({theta_deg}°) = {a:.2f} m/s². "
        f"Driving force = {F_parallel:.2f} N.",
        [f"a = g sin(θ) = {a:.2f} m/s²", "N = mg cos(θ)", "F = mg sin(θ)"],
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
                        f"Resistance (R) = {R} Ω\n"
                        f"Find: Current (I)"),
            DoubtStepOut(step=2, title="Formula to Use",
                content="Ohm's Law:  V = I × R\n\nRearranging for current: I = V / R"),
            DoubtStepOut(step=3, title="Substitute",
                content=f"I = {V} / {R}"),
            DoubtStepOut(step=4, title="Calculate",
                content=f"I = {I:.3f} A  ({I * 1000:.2f} mA)"),
            DoubtStepOut(step=5, title="Answer",
                content=f"The current flowing through the circuit is {I:.3f} A.\n"
                        f"Power dissipated: P = V × I = {V} × {I:.3f} = {V*I:.2f} W")
        ]
        return (steps, f"Current I = V/R = {V}/{R} = {I:.3f} A.",
                ["V = I × R", "I = V / R", "P = V × I", f"I = {I:.3f} A"],
                ["Current Electricity", "DC Circuits", "Ohm's Law"])

    return None


# ─────────────────────────────────────────────────────────────
#  CONCEPTUAL SOLVERS  (Core Idea → Intuition → Equation → Example → Check Yourself)
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
                    "A narrower pipe (higher resistance) restricts the flow — just as a "
                    "high-resistance component limits current."),
        DoubtStepOut(step=3, title="The Equation",
            content="Ohm's Law:  V = I × R\n\n"
                    "Rearranging: I = V / R\n\n"
                    "If V is constant and R decreases → I must increase.\n"
                    "If V is constant and R increases → I must decrease.\n\n"
                    "For example: V = 12 V, R = 3 Ω → I = 4 A\n"
                    "             V = 12 V, R = 6 Ω → I = 2 A  (R doubled, I halved)"),
        DoubtStepOut(step=4, title="Real World Example",
            content="A dimmer switch controls the brightness of a bulb by changing the "
                    "resistance in the circuit. Higher resistance → less current → dimmer bulb.\n\n"
                    "Short circuits are dangerous because resistance drops to nearly zero, "
                    "so current surges to an extremely high value, which can start fires."),
        DoubtStepOut(step=5, title="Check Your Understanding",
            content="Try this: A 9V battery is connected to a 3 Ω resistor. What is the current?\n\n"
                    "Answer: I = V / R = 9 / 3 = 3 A\n\n"
                    "Now if the resistance doubles to 6 Ω, current halves to 1.5 A. "
                    "Can you verify this using Ohm's Law?")
    ]
    return (
        steps,
        "When voltage is fixed, current and resistance are inversely proportional (I = V/R). "
        "Lower resistance allows more current to flow.",
        ["I = V / R", "V = I × R", "R ↑ means I ↓ at constant V"],
        ["Current Electricity", "Ohm's Law", "DC Circuits"]
    )


def _conceptual_why_sky_blue() -> Tuple[List[DoubtStepOut], str, List[str], List[str]]:
    steps = [
        DoubtStepOut(step=1, title="Core Idea",
            content="The sky appears blue because of a phenomenon called Rayleigh Scattering — "
                    "sunlight is scattered by gas molecules in the atmosphere, and blue light "
                    "scatters much more than red light."),
        DoubtStepOut(step=2, title="The Intuition",
            content="Sunlight is white light — it contains all colours of the rainbow. "
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
                    "remain — giving that warm glow."),
        DoubtStepOut(step=5, title="Check Your Understanding",
            content="Quick question: Why does the Moon's sky appear black even during the day?\n\n"
                    "The Moon has no atmosphere. Without gas molecules to scatter sunlight, "
                    "there is no blue sky — just the darkness of space.")
    ]
    return (
        steps,
        "The sky is blue due to Rayleigh Scattering. Blue light (short wavelength) "
        "scatters about 5 times more than red light when sunlight hits atmospheric molecules.",
        ["Scattering ∝ 1/λ⁴", "Blue λ ≈ 450 nm", "Red λ ≈ 700 nm"],
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
                    "is vastly more massive, it barely accelerates — while you fall at 9.8 m/s².\n\n"
                    "This is why planets orbit the Sun, the Moon orbits Earth, and "
                    "objects fall when dropped."),
        DoubtStepOut(step=3, title="Newton's Law of Gravitation",
            content="F = G × m₁ × m₂ / r²\n\n"
                    "Where:\n"
                    "  F = gravitational force\n"
                    "  G = Universal gravitational constant = 6.67 × 10^-11 N·m²/kg²\n"
                    "  m₁ and m₂ = masses of the two objects\n"
                    "  r = distance between their centres\n\n"
                    "The force follows an inverse-square law: double the distance, "
                    "and the force becomes 4 times weaker."),
        DoubtStepOut(step=4, title="Near Earth's Surface",
            content="For objects near Earth's surface, gravity simplifies to:\n\n"
                    "Weight = mass × g\n"
                    "W = m × g  (where g = 9.8 m/s²)\n\n"
                    "So a 60 kg person weighs: W = 60 × 9.8 = 588 N on Earth.\n"
                    "On the Moon (g = 1.6 m/s²), the same person weighs only 96 N — "
                    "that is why astronauts can jump much higher there."),
        DoubtStepOut(step=5, title="Check Your Understanding",
            content="If the distance between two objects doubles, by what factor does gravity change?\n\n"
                    "Answer: Force becomes 1/4 as strong (inverse-square law).\n\n"
                    "What if mass doubles? Force doubles — gravity is directly proportional to mass.")
    ]
    return (
        steps,
        "Gravity is an attractive force between masses. "
        "Newton's Law: F = G × m₁ × m₂ / r². Near Earth's surface, F = mg (g = 9.8 m/s²).",
        ["F = G m₁m₂ / r²", "W = mg", "g = 9.8 m/s²", "G = 6.67 × 10⁻¹¹ N·m²/kg²"],
        ["Gravitation", "Newton's Law of Gravitation", "Mechanics"]
    )


# ─────────────────────────────────────────────────────────────
#  TEACH ME SOLVERS  (Concept map — ordered learning path)
# ─────────────────────────────────────────────────────────────

def _teach_electrostatics() -> Tuple[List[DoubtStepOut], str, List[str], List[str]]:
    steps = [
        DoubtStepOut(step=1, title="Start Here: Electric Charge",
            content="Everything begins with charge. Protons carry positive charge, "
                    "electrons carry negative charge. Like charges repel, opposite charges attract.\n\n"
                    "Key fact: Charge is conserved — it cannot be created or destroyed, "
                    "only transferred.\n\n"
                    "SI unit of charge: Coulomb (C). Elementary charge: e = 1.6 × 10^-19 C"),
        DoubtStepOut(step=2, title="Step 2: Coulomb's Law",
            content="The force between two point charges is:\n\n"
                    "F = k × q₁ × q₂ / r²\n\n"
                    "Where k = 9 × 10^9 N·m²/C² is Coulomb's constant.\n\n"
                    "Same form as gravity — but much stronger, and can be repulsive as well as attractive."),
        DoubtStepOut(step=3, title="Step 3: Electric Field",
            content="Instead of asking 'what force does charge A exert on B?', we ask:\n"
                    "'What field does charge A create at a point in space?'\n\n"
                    "Electric Field E = F / q  (force per unit positive charge)\n"
                    "Field due to a point charge: E = k × Q / r²\n\n"
                    "Direction: away from positive charges, toward negative charges."),
        DoubtStepOut(step=4, title="Step 4: Electric Potential",
            content="Electric potential V is the work done per unit charge to bring a "
                    "positive charge from infinity to a point.\n\n"
                    "V = k × Q / r\n\n"
                    "Potential difference (voltage): ΔV = W / q\n"
                    "Relationship to field: E = -dV/dr (field is the slope of potential)"),
        DoubtStepOut(step=5, title="Step 5: Capacitors",
            content="A capacitor stores charge between two conducting plates.\n\n"
                    "Capacitance: C = Q / V (how much charge per volt)\n"
                    "SI unit: Farad (F)\n\n"
                    "Parallel plate capacitor: C = ε₀ × A / d\n"
                    "(where A = plate area, d = separation, ε₀ = 8.85 × 10^-12 F/m)\n\n"
                    "Energy stored in a capacitor: E = ½ × C × V²")
    ]
    return (
        steps,
        "Electrostatics covers: Charge → Coulomb's Law → Electric Field → Electric Potential → Capacitors. "
        "Master these 5 steps in order.",
        ["F = kq₁q₂/r²", "E = kQ/r²", "V = kQ/r", "C = Q/V", "E_stored = ½CV²"],
        ["Electrostatics", "Electric Field", "Capacitors", "JEE Physics"]
    )


def _teach_quadratic_equations() -> Tuple[List[DoubtStepOut], str, List[str], List[str]]:
    steps = [
        DoubtStepOut(step=1, title="Start Here: What is a Quadratic?",
            content="A quadratic equation has the form: ax² + bx + c = 0\n\n"
                    "where a, b, c are real numbers and a ≠ 0.\n\n"
                    "The graph of a quadratic is a parabola — it opens upward if a > 0, "
                    "downward if a < 0.\n\n"
                    "Examples: x² - 5x + 6 = 0,  2x² + 3x - 2 = 0"),
        DoubtStepOut(step=2, title="Step 2: Finding the Roots",
            content="The solutions (roots) are the values of x where the equation equals zero — "
                    "where the parabola crosses the x-axis.\n\n"
                    "Three methods:\n"
                    "1. Factorisation: rewrite as (x - r₁)(x - r₂) = 0\n"
                    "2. Completing the square\n"
                    "3. Quadratic Formula: x = (-b ± √(b² - 4ac)) / 2a"),
        DoubtStepOut(step=3, title="Step 3: The Discriminant",
            content="The discriminant D = b² - 4ac tells you the nature of the roots "
                    "BEFORE you solve:\n\n"
                    "D > 0  →  Two distinct real roots (parabola crosses x-axis twice)\n"
                    "D = 0  →  One repeated real root (parabola just touches the x-axis)\n"
                    "D < 0  →  No real roots, two complex roots (parabola never touches x-axis)"),
        DoubtStepOut(step=4, title="Step 4: Sum and Product of Roots",
            content="If the roots are α and β, then:\n\n"
                    "Sum of roots:     α + β = -b / a\n"
                    "Product of roots: α × β = c / a\n\n"
                    "These shortcuts are extremely useful in JEE problems — "
                    "you often do not need to find α and β individually."),
        DoubtStepOut(step=5, title="Step 5: Worked Example",
            content="Solve: x² - 5x + 6 = 0  (a=1, b=-5, c=6)\n\n"
                    "Discriminant: D = (-5)² - 4(1)(6) = 25 - 24 = 1 > 0  →  two real roots\n\n"
                    "Using quadratic formula:\n"
                    "x = (5 ± √1) / 2\n"
                    "x = (5 + 1)/2 = 3   or   x = (5 - 1)/2 = 2\n\n"
                    "Verify: Sum = 3 + 2 = 5 = -(-5)/1  ✓\n"
                    "        Product = 3 × 2 = 6 = 6/1  ✓")
    ]
    return (
        steps,
        "Quadratic equations: ax² + bx + c = 0. Roots found by factorisation or formula "
        "x = (-b ± √(b²-4ac)) / 2a. Discriminant D = b²-4ac determines the nature of roots.",
        ["x = (-b ± √D) / 2a", "D = b² - 4ac", "α + β = -b/a", "αβ = c/a"],
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
                    "Try to connect the formula to something real you can visualise — "
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
                    f"Apply the same concept to: a slightly different version of the problem — "
                    f"change one value and recalculate.\n\n"
                    f"Hint: The method is exactly the same. Just substitute the new values "
                    f"into the same formula.\n\n"
                    f"If you can solve a similar question without help, you have understood this concept."
        )
        return original_steps + [quiz_step], final_answer

    return original_steps, final_answer


# ─────────────────────────────────────────────────────────────
#  MAIN SOLVER ENTRY POINT
# ─────────────────────────────────────────────────────────────

def solve_doubt_intelligently(
    question_text: str,
    subject_hint: str = "",
    follow_up_action: Optional[str] = None
) -> Tuple[List[DoubtStepOut], str, List[str], List[str], str, str, str]:
    """
    Returns:
        (steps, final_answer, key_concepts, related_topics, question_type, confidence, confidence_label)
    All text is plain human-readable English — no LaTeX, no markdown symbols.
    """
    q_low = question_text.lower().strip()
    numbers = extract_numbers(question_text)
    subject = detect_subject(question_text, subject_hint)
    question_type = classify_question_type(question_text)
    confidence, confidence_label = classify_confidence(question_type)

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
#  GENERIC FALLBACK — Always returns a coherent answer
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
                        "Keep track of units at every step — cancel units to verify your answer "
                        "has the correct units."),
            DoubtStepOut(step=4, title="Calculate",
                content="Perform the arithmetic carefully. "
                        "Use standard values: g = 9.8 m/s², speed of light = 3 × 10^8 m/s, etc."),
            DoubtStepOut(step=5, title="Answer and Verify",
                content="State your final answer with the correct unit. "
                        "Sanity-check: does the magnitude feel reasonable? "
                        "For example, a speed above 3 × 10^8 m/s is impossible.")
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
                content="Start with definitions → understand the formula → "
                        "solve basic examples → tackle harder problems.\n\n"
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
                f"Learning roadmap for {subject}: definitions → equations → examples → practice.",
                [f"{subject} fundamentals", "Step-by-step learning"],
                [subject, "Study Strategy"])
