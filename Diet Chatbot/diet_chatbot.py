"""
Diet Plan Generator - Gradio web chatbot (Python 3.8+).

Install:  pip install gradio
Run:      python diet_chatbot_gradio.py      (then open the link shown in the terminal)

The logic (BMI, BMR, TDEE, meal database, 7-day plan, results, grocery list) is the
same as the command-line version. Only the "look" changed: the chat now runs in the
browser, with quick-reply buttons and a live dashboard on the right.
"""

import os
import html
import random
import inspect
import tempfile
import textwrap

import gradio as gr

# ------------------------------------------------------------------
# CONSTANTS (all the fixed numbers and choices live here)
# ------------------------------------------------------------------
MEAL_SLOTS = ["breakfast", "lunch", "snack", "dinner"]
SLOT_SPLIT = {"breakfast": 0.25, "lunch": 0.35, "snack": 0.10, "dinner": 0.30}
SLOT_ICON = {"breakfast": "🍳", "lunch": "🍛", "snack": "🍎", "dinner": "🌙"}

ACTIVITY_FACTOR = {"sedentary": 1.2, "light": 1.375, "moderate": 1.55, "active": 1.725}
GOAL_FACTOR = {"weight loss": 0.80, "maintenance": 1.0, "muscle gain": 1.10}
PROTEIN_PER_KG = {"weight loss": 1.2, "maintenance": 1.0, "muscle gain": 1.6}
MIN_CALORIES = {"male": 1500, "female": 1200}

# A higher rank can eat everything a lower rank can (vegan < veg < eggetarian < nonveg)
DIET_RANK = {"vegan": 0, "veg": 1, "eggetarian": 2, "nonveg": 3}

# Words the user might type for an allergy -> the allergen tag used in our meal database
ALLERGY_ALIASES = {
    "milk": "dairy", "lactose": "dairy", "wheat": "gluten", "peanut": "nuts",
    "peanuts": "nuts", "almond": "nuts", "cashew": "nuts", "nut": "nuts",
    "eggs": "egg", "prawn": "shellfish", "prawns": "shellfish",
}

# If the user mentions any of these, we do NOT make a plan
RISKY_WORDS = ["pregnan", "kidney", "cancer", "eating disorder", "anorexia", "bulimia", "binge"]

PROTEIN_TIPS = {
    "vegan": "tofu, soya chunks, lentils and sprouts",
    "veg": "paneer, curd, dal and sprouts",
    "eggetarian": "eggs, paneer, dal and sprouts",
    "nonveg": "chicken, fish, eggs and dal",
}

PLAN_FILE = "diet_plan.txt"

# The questions, in the order they are asked
STEPS = ["name", "age", "gender", "height", "weight",
         "activity", "goal", "diet", "allergies", "conditions"]

CHOICES = {
    "gender": ["male", "female"],
    "activity": ["sedentary", "light", "moderate", "active"],
    "goal": ["weight loss", "maintenance", "muscle gain"],
    "diet": ["veg", "nonveg", "vegan", "eggetarian"],
}

# key -> (lowest, highest, unit, whole number only?)
NUMBER_RULES = {
    "age": (15, 80, "years", True),
    "height": (100, 250, "cm", False),
    "weight": (30, 250, "kg", False),
}

QUESTIONS = {
    "name": "What is your **name**? ✍️",
    "age": "How **old** are you (in years)? 🎂",
    "gender": "What is your **gender**?",
    "height": "What is your **height** in cm? 📏",
    "weight": "What is your **weight** in kg? ⚖️",
    "activity": ("How **active** are you?\n\n"
                 "- **sedentary** = little or no exercise\n"
                 "- **light** = 1-3 days a week\n"
                 "- **moderate** = 3-5 days a week\n"
                 "- **active** = 6-7 days a week"),
    "goal": "What is your **goal**? 🎯",
    "diet": "What is your **diet preference**? 🥗",
    "allergies": "Do you have any **food allergies**? (e.g. *peanuts, milk, gluten*) - or type **none**",
    "conditions": "Do you have any **medical conditions**? (e.g. *diabetes, thyroid*) - or type **none**",
}

# ------------------------------------------------------------------
# MEAL DATABASE  (calories and protein are for ONE normal serving)
# ------------------------------------------------------------------


def make_meal(name, calories, protein, diet, allergens, ingredients):
    """Pack the details of one meal into a dictionary."""
    return {"name": name, "calories": calories, "protein": protein, "diet": diet,
            "allergens": allergens, "ingredients": ingredients}


MEALS = {
    "breakfast": [
        make_meal("Veg Poha with Peanuts", 320, 8, "vegan", ["nuts"],
                  ["poha", "onion", "peanuts", "green peas", "curry leaves"]),
        make_meal("Moong Dal Cheela", 280, 14, "vegan", [],
                  ["moong dal", "onion", "tomato", "green chilli", "coriander"]),
        make_meal("Idli with Sambar (3 pcs)", 300, 10, "vegan", [],
                  ["idli batter", "toor dal", "mixed vegetables", "tamarind"]),
        make_meal("Vegetable Upma", 290, 7, "vegan", ["gluten"],
                  ["semolina", "onion", "carrot", "green peas", "mustard seeds"]),
        make_meal("Besan Chilla with Mint Chutney", 270, 13, "vegan", [],
                  ["besan", "onion", "tomato", "mint", "coriander"]),
        make_meal("Paneer Paratha with Curd", 420, 17, "veg", ["gluten", "dairy"],
                  ["whole wheat flour", "paneer", "curd", "coriander"]),
        make_meal("Banana Almond Oats Porridge", 340, 12, "veg", ["dairy", "nuts", "gluten"],
                  ["oats", "milk", "banana", "almonds"]),
        make_meal("Masala Omelette with Toast", 330, 17, "eggetarian", ["egg", "gluten"],
                  ["eggs", "onion", "tomato", "bread", "green chilli"]),
        make_meal("Egg Bhurji with Roti", 360, 18, "eggetarian", ["egg", "gluten"],
                  ["eggs", "onion", "tomato", "whole wheat flour", "green chilli"]),
        make_meal("Chicken Keema Sandwich", 380, 24, "nonveg", ["gluten"],
                  ["chicken mince", "bread", "onion", "tomato", "mint"]),
    ],
    "lunch": [
        make_meal("Dal Tadka, Brown Rice & Salad", 520, 18, "vegan", [],
                  ["toor dal", "brown rice", "cucumber", "tomato", "onion", "garlic"]),
        make_meal("Rajma Chawal", 560, 19, "vegan", [],
                  ["kidney beans", "rice", "onion", "tomato", "ginger", "garlic"]),
        make_meal("Chole with 2 Roti", 540, 20, "vegan", ["gluten"],
                  ["chickpeas", "whole wheat flour", "onion", "tomato", "ginger"]),
        make_meal("Mixed Veg Curry, Roti & Dal", 500, 17, "vegan", ["gluten"],
                  ["mixed vegetables", "whole wheat flour", "toor dal", "onion", "tomato"]),
        make_meal("Moong Dal Veg Khichdi", 470, 16, "vegan", [],
                  ["rice", "moong dal", "carrot", "green peas", "cumin"]),
        make_meal("Paneer Bhurji, 2 Roti & Salad", 580, 28, "veg", ["dairy", "gluten"],
                  ["paneer", "whole wheat flour", "onion", "tomato", "cucumber"]),
        make_meal("Palak Paneer with Rice", 550, 24, "veg", ["dairy"],
                  ["paneer", "spinach", "rice", "onion", "tomato", "garlic"]),
        make_meal("Curd Rice with Veg Sambar", 480, 15, "veg", ["dairy"],
                  ["rice", "curd", "toor dal", "mixed vegetables", "tamarind"]),
        make_meal("Egg Curry with Rice", 540, 25, "eggetarian", ["egg"],
                  ["eggs", "rice", "onion", "tomato", "ginger", "garlic"]),
        make_meal("Chicken Curry, Rice & Salad", 600, 38, "nonveg", [],
                  ["chicken", "rice", "onion", "tomato", "ginger", "garlic", "cucumber"]),
    ],
    "snack": [
        make_meal("Roasted Chana", 150, 8, "vegan", [],
                  ["roasted chickpeas", "chaat masala"]),
        make_meal("Fruit Chaat", 120, 2, "vegan", [],
                  ["apple", "banana", "orange", "lemon", "chaat masala"]),
        make_meal("Sprouts Salad", 140, 9, "vegan", [],
                  ["sprouted moong", "onion", "tomato", "lemon", "coriander"]),
        make_meal("Mixed Nuts Handful", 180, 6, "vegan", ["nuts"],
                  ["almonds", "walnuts", "cashews"]),
        make_meal("Murmura Bhel", 130, 3, "vegan", [],
                  ["puffed rice", "onion", "tomato", "lemon", "coriander"]),
        make_meal("Banana with Peanut Butter", 200, 6, "vegan", ["nuts"],
                  ["banana", "peanut butter"]),
        make_meal("Makhana & Masala Buttermilk", 110, 4, "veg", ["dairy"],
                  ["makhana", "buttermilk", "cumin"]),
        make_meal("Paneer Tikka Cubes", 170, 12, "veg", ["dairy"],
                  ["paneer", "curd", "capsicum"]),
        make_meal("Boiled Eggs with Pepper", 150, 12, "eggetarian", ["egg"],
                  ["eggs", "black pepper"]),
        make_meal("Chicken Tikka (4 pcs)", 190, 22, "nonveg", ["dairy"],
                  ["chicken", "curd", "capsicum"]),
    ],
    "dinner": [
        make_meal("Veg Dalia Khichdi", 400, 13, "vegan", ["gluten"],
                  ["broken wheat", "moong dal", "carrot", "green peas", "onion"]),
        make_meal("Lauki Sabzi, 2 Roti & Dal", 420, 15, "vegan", ["gluten"],
                  ["bottle gourd", "whole wheat flour", "toor dal", "tomato", "cumin"]),
        make_meal("Masoor Dal with Jeera Rice", 450, 16, "vegan", [],
                  ["masoor dal", "rice", "onion", "tomato", "cumin"]),
        make_meal("Soya Chunk Curry, 2 Roti", 480, 28, "vegan", ["soy", "gluten"],
                  ["soya chunks", "whole wheat flour", "onion", "tomato", "ginger"]),
        make_meal("Ragi Roti with Mixed Veg", 400, 11, "vegan", [],
                  ["ragi flour", "mixed vegetables", "onion", "tomato"]),
        make_meal("Paneer Tikka Masala, 2 Roti", 520, 27, "veg", ["dairy", "gluten"],
                  ["paneer", "whole wheat flour", "onion", "tomato", "cream"]),
        make_meal("Matar Paneer with Jeera Rice", 500, 22, "veg", ["dairy"],
                  ["paneer", "green peas", "rice", "onion", "tomato", "cumin"]),
        make_meal("Veg Pulao with Raita", 440, 13, "veg", ["dairy"],
                  ["rice", "mixed vegetables", "curd", "cucumber", "cumin"]),
        make_meal("Egg Curry with 2 Roti", 450, 22, "eggetarian", ["egg", "gluten"],
                  ["eggs", "whole wheat flour", "onion", "tomato", "ginger"]),
        make_meal("Grilled Chicken, Veg & Roti", 500, 40, "nonveg", ["gluten"],
                  ["chicken", "mixed vegetables", "whole wheat flour", "garlic", "black pepper"]),
    ],
}


# ------------------------------------------------------------------
# INPUT CHECKING (each function returns  value, error_message)
# ------------------------------------------------------------------
def clean(text):
    """Lower-case a text and remove spaces and hyphens so 'Non-Veg' matches 'nonveg'."""
    return text.lower().replace(" ", "").replace("-", "")


def parse_name(text):
    """Accept a name made of letters (spaces allowed), at least 2 characters."""
    if len(text) >= 2 and text.replace(" ", "").isalpha():
        return text.title(), None
    return None, "😅 Please use **letters only** (at least 2), for example: *Priya*"


def parse_number(text, low, high, unit, whole):
    """Accept a number between low and high (whole numbers only if whole=True)."""
    try:
        value = float(text)
    except ValueError:
        return None, "😅 That is not a number. Please type digits only, for example: *65*"
    if whole and value != int(value):
        return None, "😅 Please enter a **whole number** (no decimals)."
    if not low <= value <= high:
        return None, f"😅 Please enter a sensible value between **{low} and {high} {unit}**."
    return (int(value) if whole else value), None


def parse_choice(text, options):
    """Accept the number or the name of one of the options."""
    numbers = [str(n) for n in range(1, len(options) + 1)]
    if text in numbers:
        return options[int(text) - 1], None
    for option in options:
        if clean(text) == clean(option):
            return option, None
    return None, "😅 Sorry, that is not a valid choice. Type the **number** or the **name**."


def parse_list(text):
    """Accept a comma-separated list of words; 'none' gives an empty list."""
    text = text.lower()
    if text in ("none", "no", "nil", "na", "n/a"):
        return [], None
    items = [part.strip() for part in text.split(",") if part.strip()]
    if items and all(item.replace(" ", "").replace("-", "").isalpha() for item in items):
        return items, None
    return None, "😅 Please use **letters only**, separated by commas (or type **none**)."


def parse_answer(key, text):
    """Check the answer for the current question; returns (value, error_message)."""
    if key == "name":
        return parse_name(text)
    if key in NUMBER_RULES:
        low, high, unit, whole = NUMBER_RULES[key]
        return parse_number(text, low, high, unit, whole)
    if key in CHOICES:
        return parse_choice(text, CHOICES[key])
    return parse_list(text)          # allergies and conditions


def ask_text(key):
    """Return the question text (with numbered options for choice questions)."""
    text = QUESTIONS[key]
    if key in CHOICES:
        menu = "   ".join(f"**{n}.** {name}" for n, name in enumerate(CHOICES[key], start=1))
        text += "\n\n" + menu + "\n\n*Type the number or the name - or tap a button below.*"
    return text


# ------------------------------------------------------------------
# CALCULATIONS
# ------------------------------------------------------------------
def calculate_bmi(weight, height_cm):
    """Return BMI = weight (kg) / height (m) squared."""
    return weight / (height_cm / 100) ** 2


def bmi_category(bmi):
    """Return the BMI category name."""
    if bmi < 18.5:
        return "underweight"
    if bmi < 25:
        return "normal"
    if bmi < 30:
        return "overweight"
    return "obese"


def calculate_bmr(profile):
    """Return BMR (kcal/day) using the Mifflin-St Jeor equation."""
    base = 10 * profile["weight"] + 6.25 * profile["height"] - 5 * profile["age"]
    if profile["gender"] == "male":
        return base + 5
    return base - 161


def calculate_targets(profile):
    """Return a dictionary with BMI, BMR, TDEE, calorie target and macro targets."""
    bmi = calculate_bmi(profile["weight"], profile["height"])
    bmr = calculate_bmr(profile)
    tdee = bmr * ACTIVITY_FACTOR[profile["activity"]]

    calories = tdee * GOAL_FACTOR[profile["goal"]]
    safe_minimum = MIN_CALORIES[profile["gender"]]
    floor_applied = calories < safe_minimum
    if floor_applied:
        calories = safe_minimum              # never go below the safe minimum

    protein = PROTEIN_PER_KG[profile["goal"]] * profile["weight"]   # grams
    fat = calories * 0.28 / 9                                       # 1 g fat = 9 kcal
    carbs = max(0, (calories - protein * 4 - fat * 9) / 4)          # 1 g protein/carb = 4 kcal

    return {"bmi": bmi, "category": bmi_category(bmi), "bmr": bmr, "tdee": tdee,
            "calories": calories, "floor_applied": floor_applied, "safe_minimum": safe_minimum,
            "protein": protein, "fat": fat, "carbs": carbs}


def has_risky_words(text):
    """Return True if the text mentions pregnancy, kidney disease, cancer or an eating disorder."""
    text = text.lower()
    for word in RISKY_WORDS:
        if word in text:
            return True
    return False


# ------------------------------------------------------------------
# MEAL PLAN
# ------------------------------------------------------------------
def has_allergen(meal, allergies):
    """Return True if the meal contains any of the user's allergens."""
    text = meal["name"].lower() + " " + " ".join(meal["ingredients"])
    for item in allergies:
        tag = ALLERGY_ALIASES.get(item, item)        # turn 'milk' into 'dairy', etc.
        if tag in meal["allergens"] or item in text:
            return True
    return False


def get_eligible_meals(slot, profile):
    """Return the meals of a slot that match the user's diet and have no allergens."""
    user_rank = DIET_RANK[profile["diet"]]
    eligible = []
    for meal in MEALS[slot]:
        if DIET_RANK[meal["diet"]] <= user_rank and not has_allergen(meal, profile["allergies"]):
            eligible.append(meal)
    return eligible


def make_entry(meal, calorie_target):
    """Scale a meal's portion (0.5x to 2x) so it is close to the calorie target."""
    portion = round(calorie_target / meal["calories"] * 4) / 4   # round to nearest 0.25
    portion = max(0.5, min(2.0, portion))                       # keep it between 0.5x and 2x
    return {"meal": meal, "portion": portion,
            "calories": round(meal["calories"] * portion),
            "protein": round(meal["protein"] * portion, 1)}


def build_plan(profile, t):
    """Build a 7-day plan (a list of 7 dictionaries); return None if some slot has no meals."""
    choices = {}
    for slot in MEAL_SLOTS:
        eligible = get_eligible_meals(slot, profile)
        if not eligible:
            return None
        # put meals of the highest diet level first, so e.g. non-veg users see chicken too
        choices[slot] = sorted(eligible, key=lambda m: DIET_RANK[m["diet"]], reverse=True)

    plan = []
    for day in range(7):
        day_plan = {}
        for slot in MEAL_SLOTS:
            meal = choices[slot][day % len(choices[slot])]     # rotate through the options
            day_plan[slot] = make_entry(meal, t["calories"] * SLOT_SPLIT[slot])
        plan.append(day_plan)
    return plan


def swap_meal(plan, slot, day_number, profile, t):
    """Replace one meal with a different eligible one; return (old name, new name) or None."""
    day_plan = plan[day_number - 1]
    old_name = day_plan[slot]["meal"]["name"]
    others = [m for m in get_eligible_meals(slot, profile) if m["name"] != old_name]
    if not others:
        return None
    used_names = [d[slot]["meal"]["name"] for d in plan]
    fresh = [m for m in others if m["name"] not in used_names]   # prefer a meal not used yet
    if fresh:
        others = fresh
    new_meal = random.choice(others)
    day_plan[slot] = make_entry(new_meal, t["calories"] * SLOT_SPLIT[slot])
    return old_name, new_meal["name"]


def day_totals(day_plan):
    """Return (total calories, total protein) of one day."""
    calories = sum(day_plan[slot]["calories"] for slot in MEAL_SLOTS)
    protein = sum(day_plan[slot]["protein"] for slot in MEAL_SLOTS)
    return calories, protein


def plan_averages(plan):
    """Return the average daily calories and protein of the whole week."""
    total_calories = 0
    total_protein = 0
    for day_plan in plan:
        calories, protein = day_totals(day_plan)
        total_calories += calories
        total_protein += protein
    return total_calories / len(plan), total_protein / len(plan)


def project_weight(profile, tdee, avg_calories):
    """Estimate weight after 2, 4, 8 and 12 weeks (7700 kcal = 1 kg)."""
    weight = profile["weight"]
    height = profile["height"]
    raw_weekly = (avg_calories - tdee) * 7 / 7700          # kg change per week, before limits
    weekly = max(-1.0, min(0.5, raw_weekly))               # loss max 1 kg/wk, gain max 0.5 kg/wk
    lowest = min(weight, 18.5 * (height / 100) ** 2)       # never project below BMI 18.5
    results = []
    for weeks in (2, 4, 8, 12):
        new_weight = max(lowest, weight + weekly * weeks)
        results.append((weeks, new_weight, new_weight - weight, calculate_bmi(new_weight, height)))
    return results, raw_weekly, weekly, lowest


def count_ingredients(plan):
    """Return a dictionary: ingredient -> number of meals in the plan that use it."""
    counts = {}
    for day_plan in plan:
        for slot in MEAL_SLOTS:
            for ingredient in day_plan[slot]["meal"]["ingredients"]:
                counts[ingredient] = counts.get(ingredient, 0) + 1
    return counts


def text_progress_bar(percent):
    """Return a 20-character bar of █ and ░ followed by the percentage."""
    filled = int(min(percent, 100) / 100 * 20)
    return "█" * filled + "░" * (20 - filled) + f" {percent:.0f}%"


# ------------------------------------------------------------------
# CONTENT BLOCKS
# Every section is built as a list of blocks:
#   ("heading", text)  ("table", headers, rows, aligns, total_row)  ("note", text)
# The SAME blocks are shown in the chat (markdown) and saved to the .txt file (boxed text).
# ------------------------------------------------------------------
def profile_blocks(profile, t):
    """Blocks for the user's details, calculated numbers and warnings."""
    details = [
        ["Name", profile["name"]],
        ["Age / Gender", f"{profile['age']} / {profile['gender']}"],
        ["Height / Weight", f"{profile['height']:g} cm / {profile['weight']:g} kg"],
        ["Activity level", profile["activity"]],
        ["Goal", profile["goal"]],
        ["Diet", profile["diet"]],
        ["Allergies", ", ".join(profile["allergies"]) or "none"],
        ["Medical conditions", ", ".join(profile["conditions"]) or "none"],
    ]
    numbers = [
        ["BMI", f"{t['bmi']:.1f} ({t['category']})"],
        ["BMR (Mifflin-St Jeor)", f"{t['bmr']:.0f} kcal/day"],
        ["TDEE (BMR x activity)", f"{t['tdee']:.0f} kcal/day"],
        ["Daily calorie target", f"{t['calories']:.0f} kcal/day"],
        ["Protein", f"{t['protein']:.0f} g/day"],
        ["Fat (28% of calories)", f"{t['fat']:.0f} g/day"],
        ["Carbs (the rest)", f"{t['carbs']:.0f} g/day"],
    ]
    blocks = [
        ("heading", "📋 Your profile"),
        ("table", ["Detail", "Value"], details, ["l", "l"], None),
        ("heading", "📊 Your numbers"),
        ("table", ["Metric", "Value"], numbers, ["l", "r"], None),
    ]
    if t["floor_applied"]:
        blocks.append(("note", f"⚠️ Your calories were raised to the safe minimum of "
                               f"{t['safe_minimum']} kcal."))
    if t["category"] == "underweight" and profile["goal"] == "weight loss":
        blocks.append(("note", "⚠️ WARNING: your BMI says you are underweight, but your goal is "
                               "weight loss. Losing more weight may harm your health. Please talk "
                               "to a doctor, or consider 'maintenance' or 'muscle gain' instead."))
    return blocks


def day_blocks(plan, day_number):
    """Blocks for one day: a table with calories and protein per meal and the daily total."""
    day_plan = plan[day_number - 1]
    rows = []
    for slot in MEAL_SLOTS:
        entry = day_plan[slot]
        rows.append([f"{SLOT_ICON[slot]} {slot.title()}", entry["meal"]["name"],
                     f"{entry['portion']:g}x", entry["calories"], f"{entry['protein']:.1f}"])
    calories, protein = day_totals(day_plan)
    total_row = ["Total", "", "", calories, f"{protein:.1f}"]
    return [("heading", f"📅 Day {day_number}"),
            ("table", ["Meal", "Dish", "Portion", "Kcal", "Prot (g)"], rows,
             ["l", "l", "r", "r", "r"], total_row)]


def plan_blocks(plan):
    """Blocks for all 7 days."""
    blocks = []
    for day_number in range(1, 8):
        blocks += day_blocks(plan, day_number)
    return blocks


def targets_blocks(profile, plan, t):
    """Blocks comparing the daily targets with the plan's weekly average."""
    avg_calories, avg_protein = plan_averages(plan)
    calorie_percent = avg_calories / t["calories"] * 100
    protein_percent = avg_protein / t["protein"] * 100
    rows = [
        ["Calories", f"{t['calories']:.0f} kcal", f"{avg_calories:.0f} kcal",
         text_progress_bar(calorie_percent)],
        ["Protein", f"{t['protein']:.0f} g", f"{avg_protein:.0f} g",
         text_progress_bar(protein_percent)],
    ]
    blocks = [("heading", "🎯 Targets vs your plan (weekly average)"),
              ("table", ["Nutrient", "Daily target", "Plan average", "Progress"], rows,
               ["l", "r", "r", "l"], None)]
    if protein_percent < 85:
        blocks.append(("note", "💡 Tip: your plan's protein is below 85% of your target. Try adding "
                               "extra " + PROTEIN_TIPS[profile["diet"]] + " to your meals or snacks."))
    return blocks


def results_blocks(profile, plan, t):
    """Blocks with the expected weight and BMI after 2, 4, 8 and 12 weeks."""
    avg_calories, _ = plan_averages(plan)
    results, raw_weekly, weekly, lowest = project_weight(profile, t["tdee"], avg_calories)
    difference = avg_calories - t["tdee"]
    rows = [["Start (now)", f"{profile['weight']:.1f}", "-", f"{t['bmi']:.1f}"]]
    for weeks, new_weight, change, new_bmi in results:
        rows.append([f"After {weeks} weeks", f"{new_weight:.1f}", f"{change:+.1f}", f"{new_bmi:.1f}"])
    blocks = [
        ("heading", "📈 Expected results if you follow the plan"),
        ("note", f"Plan average: {avg_calories:.0f} kcal/day | TDEE: {t['tdee']:.0f} kcal/day | "
                 f"Difference: {difference:+.0f} kcal/day"),
        ("table", ["When", "Expected weight (kg)", "Change (kg)", "New BMI"], rows,
         ["l", "r", "r", "r"], None),
    ]
    if weekly != raw_weekly:
        blocks.append(("note", f"The raw estimate was {raw_weekly:+.2f} kg/week, but it is limited "
                               "to a safe maximum (loss 1 kg/week, gain 0.5 kg/week)."))
    if profile["weight"] + weekly * 12 < lowest:
        blocks.append(("note", "The projection stops at a healthy BMI of 18.5 (or your current "
                               "weight if you are already below it)."))
    blocks.append(("note", "⚠️ These are only ESTIMATES (based on 7700 kcal = 1 kg). Real results "
                           "vary from person to person and are NOT guaranteed."))
    return blocks


def grocery_blocks(plan):
    """Blocks with each ingredient and how many meals use it."""
    counts = count_ingredients(plan)
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))   # most used first
    rows = [[name.title(), number] for name, number in ordered]
    return [("heading", "🛒 Grocery list (7 days, 28 meals)"),
            ("table", ["Ingredient", "Meals using it"], rows, ["l", "r"], None)]


def disclaimer_blocks(profile):
    """Blocks with the medical disclaimer (extra warning if conditions were entered)."""
    blocks = [("heading", "🏥 Disclaimer"),
              ("note", "This plan is for general information only. Please consult a doctor or a "
                       "registered dietitian before starting any diet.")]
    if profile["conditions"]:
        blocks.append(("note", "⚠️ You mentioned: " + ", ".join(profile["conditions"]) + ". Your "
                               "doctor must approve this plan first, because medical conditions "
                               "can change your needs."))
    return blocks


def refusal_blocks():
    """Blocks explaining that no plan is made for pregnancy, kidney disease, cancer, etc."""
    return [("heading", "🚫 Sorry, I cannot make a plan"),
            ("note", "You mentioned pregnancy, kidney disease, cancer or an eating disorder. These "
                     "need a personalised plan from a doctor or a registered dietitian, so I will "
                     "not generate a diet plan. Please see a professional. Take care! 💛")]


def commands_blocks():
    """Blocks listing the commands the chatbot understands."""
    rows = [
        ["show my plan", "see the full 7-day plan again"],
        ["show day 3", "see one day (1 to 7)"],
        ["swap dinner for day 3", "change any meal on any day"],
        ["results", "expected weight after 2, 4, 8, 12 weeks"],
        ["grocery list", "ingredients and how many meals use them"],
        ["save", "create a downloadable " + PLAN_FILE],
        ["restart", "start again with new details"],
        ["quit", "end the chat"],
    ]
    return [("heading", "💬 What you can type"),
            ("table", ["Command", "What it does"], rows, ["l", "l"], None)]


# ------------------------------------------------------------------
# RENDERING BLOCKS: markdown for the chat, boxed text for the file
# ------------------------------------------------------------------
def render_markdown(blocks):
    """Turn blocks into markdown text for the chat window."""
    parts = []
    for block in blocks:
        kind = block[0]
        if kind == "heading":
            parts.append("### " + block[1])
        elif kind == "note":
            parts.append("> " + block[1])
        else:
            _, headers, rows, aligns, total_row = block
            marks = [":--" if a == "l" else "--:" for a in aligns]
            lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(marks) + " |"]
            for row in rows:
                lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
            if total_row is not None:
                bold = [f"**{cell}**" if str(cell) != "" else "" for cell in total_row]
                lines.append("| " + " | ".join(bold) + " |")
            parts.append("\n".join(lines))
    return "\n\n".join(parts)


def text_width(text):
    """Return how many terminal columns a string uses (emoji count as 2)."""
    return sum(2 if ord(ch) >= 0x1F000 else 1 for ch in text)


def pad_cell(text, width, align):
    """Pad text with spaces up to the given width (align 'l' = left, 'r' = right)."""
    gap = width - text_width(text)
    if align == "r":
        return " " * gap + text
    return text + " " * gap


def text_table(headers, rows, aligns, total_row):
    """Return a boxed text table (┌ ─ ┬ │ ┘) with aligned columns."""
    rows = [[str(cell) for cell in row] for row in rows]
    if total_row is not None:
        total_row = [str(cell) for cell in total_row]
    widths = [text_width(h) for h in headers]
    for row in rows + ([total_row] if total_row else []):
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], text_width(cell))

    def border(left, middle, right):
        return left + middle.join("─" * (w + 2) for w in widths) + right

    def line(cells):
        parts = [" " + pad_cell(c, w, a) + " " for c, w, a in zip(cells, widths, aligns)]
        return "│" + "│".join(parts) + "│"

    lines = [border("┌", "┬", "┐"), line(headers), border("├", "┼", "┤")]
    lines += [line(row) for row in rows]
    if total_row is not None:
        lines += [border("├", "┼", "┤"), line(total_row)]
    lines.append(border("└", "┴", "┘"))
    return "\n".join(lines)


def render_text(blocks):
    """Turn blocks into plain text (no colours, no markdown) for the saved file."""
    parts = []
    for block in blocks:
        kind = block[0]
        if kind == "heading":
            parts.append("\n" + block[1] + "\n" + "─" * 60)
        elif kind == "note":
            parts.append(textwrap.fill(block[1], 72))
        else:
            parts.append(text_table(*block[1:]))
    return "\n".join(parts) + "\n"


# ------------------------------------------------------------------
# CONVERSATION STATE AND COMMANDS
# ------------------------------------------------------------------
def new_state():
    """Return a fresh conversation state."""
    return {"step": "name", "profile": {}, "targets": None, "plan": None, "file": None}


def greeting_text():
    """Return the first bot message."""
    return ("Hello! 👋 I am **DietBot**. I will ask you a few quick questions and then build a "
            "**7-day Indian meal plan** just for you.\n\n"
            "*I am not a doctor - always check your plan with one.* You can type **quit** or "
            "**restart** at any time.\n\n" + ask_text("name"))


def start_over(state):
    """Reset the conversation state in place."""
    state.clear()
    state.update(new_state())


def save_report(state):
    """Write the full report to diet_plan.txt (inside a temp folder) and remember its path."""
    profile, t, plan = state["profile"], state["targets"], state["plan"]
    blocks = (profile_blocks(profile, t) + plan_blocks(plan) + targets_blocks(profile, plan, t)
              + results_blocks(profile, plan, t) + grocery_blocks(plan) + disclaimer_blocks(profile))
    path = os.path.join(tempfile.mkdtemp(), PLAN_FILE)
    with open(path, "w", encoding="utf-8") as file:
        file.write("DIET PLAN FOR " + profile["name"].upper() + "\n")
        file.write(render_text(blocks))
    state["file"] = path


def find_day_number(words):
    """Return the first number from 1 to 7 found in the words, or None."""
    for word in words:
        if word.isdecimal() and 1 <= int(word) <= 7:
            return int(word)
    return None


def find_slot(words):
    """Return the first meal slot name found in the words, or None."""
    for word in words:
        if word in MEAL_SLOTS:
            return word
    return None


def finish_profile(state):
    """All questions answered: check safety, calculate, build the plan; return bot messages."""
    profile = state["profile"]
    if has_risky_words(" ".join(profile["conditions"] + profile["allergies"])):
        state["step"] = "blocked"
        return [render_markdown(refusal_blocks()) + "\n\nType **restart** to start again."]

    t = calculate_targets(profile)
    plan = build_plan(profile, t)
    if plan is None:
        state["step"] = "blocked"
        return ["Sorry, your diet and allergies leave me with **no meals** for at least one meal "
                "time. Please try again with fewer restrictions - type **restart**."]

    state["targets"], state["plan"], state["step"] = t, plan, "chat"
    return [
        "✅ **Done! Here is your personalised plan** 🎉\n\n" + render_markdown(profile_blocks(profile, t)),
        render_markdown(plan_blocks(plan)),
        render_markdown(targets_blocks(profile, plan, t) + disclaimer_blocks(profile))
        + "\n\nTry **results**, **grocery list**, **swap dinner for day 3** or **help** - "
          "or use the buttons below. 👇",
    ]


def answer_question(state, text):
    """Handle the answer to the current question; return the bot messages."""
    key = state["step"]
    value, error = parse_answer(key, text)
    if error:
        return [error + "\n\n" + ask_text(key)]
    state["profile"][key] = value

    position = STEPS.index(key)
    if position + 1 == len(STEPS):
        return finish_profile(state)
    state["step"] = STEPS[position + 1]
    greeting = f"Nice to meet you, **{value}**! 😊\n\n" if key == "name" else ""
    return [greeting + ask_text(state["step"])]


def run_command(state, text):
    """Run a chat command (after the plan is shown); return the bot messages."""
    profile, t, plan = state["profile"], state["targets"], state["plan"]
    words = text.split()

    if text in ("show my plan", "show plan", "plan"):
        return [render_markdown(plan_blocks(plan))]
    if words[:2] == ["show", "day"] or words[:1] == ["day"]:
        day_number = find_day_number(words)
        if day_number is None:
            return ["Please give a day from 1 to 7, for example: **show day 3**"]
        return [render_markdown(day_blocks(plan, day_number))]
    if words[:1] == ["swap"]:
        slot, day_number = find_slot(words), find_day_number(words)
        if slot is None or day_number is None:
            return ["Please say it like this: **swap dinner for day 3** "
                    "(meals: breakfast, lunch, snack, dinner; days: 1 to 7)."]
        result = swap_meal(plan, slot, day_number, profile, t)
        if result is None:
            return [f"Sorry, there is no other {slot} that fits your diet and allergies."]
        return [f"🔄 Swapped **{slot}** on day {day_number}: *{result[0]}* → **{result[1]}**\n\n"
                + render_markdown(day_blocks(plan, day_number))]
    if text in ("results", "result"):
        return [render_markdown(results_blocks(profile, plan, t))]
    if text in ("grocery list", "grocery"):
        return [render_markdown(grocery_blocks(plan))]
    if text == "save":
        try:
            save_report(state)
        except OSError:
            return ["Sorry, I could not write the file. Please check the folder permissions."]
        return [f"💾 Your plan is ready as **{PLAN_FILE}** - download it from the box below the chat."]
    if text in ("help", "?"):
        return [render_markdown(commands_blocks())]
    if has_risky_words(text):
        return ["That sounds like something a doctor or dietitian should guide you on. "
                "Please consult a professional. 💛"]
    return ["🤔 Sorry, I did not understand that. Type **help** to see my commands."]


def handle_message(text, history, state):
    """Main chatbot brain: take the user's text, return the updated chat history."""
    text = text.strip()
    if not text:
        return history, state
    history = history + [{"role": "user", "content": text}]
    lowered = text.lower()

    if lowered in ("quit", "exit"):
        start_over(state)
        state["step"] = "ended"
        replies = ["Goodbye! Stay healthy! 👋 Type **restart** whenever you want to begin again."]
    elif lowered == "restart":
        start_over(state)
        history = []                                  # fresh chat window
        replies = [greeting_text()]
    elif state["step"] in ("ended", "blocked"):
        replies = ["Please type **restart** to start again."]
    elif state["step"] in STEPS:
        replies = answer_question(state, text)
    else:
        replies = run_command(state, lowered)

    for reply in replies:
        history = history + [{"role": "assistant", "content": reply}]
    return history, state


# ------------------------------------------------------------------
# DASHBOARD (HTML panel on the right) - all user text is escaped
# ------------------------------------------------------------------
def bar_html(percent, label, right_text):
    """Return one HTML progress bar (green >= 90%, amber >= 75%, red below)."""
    colour = "#10b981" if percent >= 90 else "#f59e0b" if percent >= 75 else "#ef4444"
    width = min(percent, 100)
    return (f'<div class="db-bar-row"><div class="db-bar-label"><span>{label}</span>'
            f'<span>{right_text}</span></div><div class="db-bar">'
            f'<div class="db-bar-fill" style="width:{width:.0f}%;background:{colour}"></div></div></div>')


def metric_html(label, value, small=""):
    """Return one small metric card."""
    return (f'<div class="db-metric"><div class="db-l">{label}</div>'
            f'<div class="db-v">{value}</div><div class="db-s">{small}</div></div>')


def onboarding_html(state):
    """Dashboard shown while the questions are still being answered."""
    answered = state["profile"]
    percent = len(answered) / len(STEPS) * 100
    if state["step"] == "ended":
        message = "Chat ended. Type <b>restart</b> to begin again."
    elif state["step"] == "blocked":
        message = "No plan was created. Type <b>restart</b> to try again."
    else:
        message = f"Question {min(len(answered) + 1, len(STEPS))} of {len(STEPS)}"
    chips = ""
    for key in STEPS:
        if key in answered:
            value = answered[key]
            if isinstance(value, list):
                value = ", ".join(value) or "none"
            chips += f'<span class="db-chip">{key}: <b>{html.escape(str(value))}</b></span>'
    return ('<div class="db-wrap"><div class="db-title">📊 Your Dashboard</div>'
            f'<div class="db-note">{message}</div>'
            + bar_html(percent, "Profile progress", f"{percent:.0f}%")
            + f'<div class="db-chips">{chips}</div>'
            '<div class="db-note">Answer the questions in the chat and your personal numbers '
            'will appear here. ✨</div></div>')


def dashboard_html(state):
    """Return the dashboard HTML for the current state."""
    if state["plan"] is None:
        return onboarding_html(state)

    profile, t, plan = state["profile"], state["targets"], state["plan"]
    avg_calories, avg_protein = plan_averages(plan)
    calorie_percent = avg_calories / t["calories"] * 100
    protein_percent = avg_protein / t["protein"] * 100
    results, _, _, _ = project_weight(profile, t["tdee"], avg_calories)
    _, final_weight, final_change, final_bmi = results[-1]

    category_colour = {"normal": "#10b981", "obese": "#ef4444"}.get(t["category"], "#f59e0b")
    protein_kcal, fat_kcal, carb_kcal = t["protein"] * 4, t["fat"] * 9, t["carbs"] * 4
    total_kcal = protein_kcal + fat_kcal + carb_kcal
    p_share, f_share = protein_kcal / total_kcal * 100, fat_kcal / total_kcal * 100
    c_share = 100 - p_share - f_share

    return (
        '<div class="db-wrap">'
        '<div class="db-title">📊 Your Dashboard</div>'
        f'<div class="db-note">{html.escape(profile["name"])} · {profile["goal"]} · {profile["diet"]}</div>'
        '<div class="db-grid">'
        + metric_html("BMI", f"{t['bmi']:.1f}",
                      f'<span class="db-pill" style="background:{category_colour}">{t["category"]}</span>')
        + metric_html("Daily calories", f"{t['calories']:.0f}", "kcal / day")
        + metric_html("Protein", f"{t['protein']:.0f} g", "per day")
        + metric_html("TDEE", f"{t['tdee']:.0f}", f"BMR {t['bmr']:.0f} kcal")
        + '</div>'
        '<div class="db-sub">Macro split (of calories)</div>'
        '<div class="db-stack">'
        f'<div style="width:{p_share:.0f}%;background:#10b981"></div>'
        f'<div style="width:{f_share:.0f}%;background:#f59e0b"></div>'
        f'<div style="width:{c_share:.0f}%;background:#0ea5e9"></div></div>'
        '<div class="db-legend">'
        f'<span><i style="background:#10b981"></i>Protein {t["protein"]:.0f} g</span>'
        f'<span><i style="background:#f59e0b"></i>Fat {t["fat"]:.0f} g</span>'
        f'<span><i style="background:#0ea5e9"></i>Carbs {t["carbs"]:.0f} g</span></div>'
        '<div class="db-sub">Plan vs target (weekly average)</div>'
        + bar_html(calorie_percent, "Calories", f"{avg_calories:.0f} / {t['calories']:.0f} kcal")
        + bar_html(protein_percent, "Protein", f"{avg_protein:.0f} / {t['protein']:.0f} g")
        + '<div class="db-sub">Estimate after 12 weeks</div>'
        f'<div class="db-result">{profile["weight"]:.1f} kg → <b>{final_weight:.1f} kg</b> '
        f'({final_change:+.1f} kg) · BMI {final_bmi:.1f}</div>'
        '<div class="db-note">Estimates only - not guaranteed. Consult a doctor or dietitian.</div>'
        '</div>'
    )


# ------------------------------------------------------------------
# LOOK AND FEEL
# ------------------------------------------------------------------
HEADER_HTML = """
<div class="hero">
  <div class="hero-emoji">🥗</div>
  <h1>DietBot - Diet Plan Generator</h1>
  <p>Your personal Indian meal-plan chatbot · BMI · calories · 7-day plan · grocery list</p>
</div>
"""

CSS = """
.gradio-container {max-width: 1280px !important; margin: 0 auto !important;}
.hero {text-align:center; padding: 24px 16px; border-radius: 20px; margin-bottom: 6px;
       background: linear-gradient(135deg, #10b981 0%, #0d9488 55%, #0ea5e9 100%);
       box-shadow: 0 10px 30px rgba(16,185,129,.28);}
.hero-emoji {font-size: 2.4rem; line-height: 1;}
.hero h1 {margin: 6px 0 4px; font-size: 2rem; font-weight: 800; color: #fff !important;}
.hero p {margin: 0; color: rgba(255,255,255,.92) !important; font-size: 1rem;}
.quick-row {flex-wrap: wrap !important; gap: 8px !important;}
.quick-btn {border-radius: 999px !important; min-width: 0 !important; flex: 0 0 auto !important;}
.db-wrap {border-radius: 18px; padding: 18px; border: 1px solid rgba(16,185,129,.35);
          background: linear-gradient(180deg, rgba(16,185,129,.10), rgba(14,165,233,.06));}
.db-title {font-size: 1.25rem; font-weight: 800; margin-bottom: 2px;}
.db-note {font-size: .85rem; opacity: .75; margin: 6px 0 10px;}
.db-sub {font-weight: 700; margin: 16px 0 8px; font-size: .95rem;}
.db-grid {display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 8px;}
.db-metric {border-radius: 14px; padding: 12px; background: rgba(127,127,127,.10);
            border: 1px solid rgba(127,127,127,.18);}
.db-l {font-size: .75rem; opacity: .7; text-transform: uppercase; letter-spacing: .05em;}
.db-v {font-size: 1.5rem; font-weight: 800; margin: 2px 0;}
.db-s {font-size: .78rem; opacity: .75;}
.db-pill {color: #fff; padding: 2px 10px; border-radius: 999px; font-size: .75rem; font-weight: 700;}
.db-bar-row {margin-bottom: 10px;}
.db-bar-label {display: flex; justify-content: space-between; font-size: .82rem; margin-bottom: 4px;}
.db-bar {height: 10px; border-radius: 999px; background: rgba(127,127,127,.22); overflow: hidden;}
.db-bar-fill {height: 100%; border-radius: 999px;}
.db-stack {display: flex; height: 12px; border-radius: 999px; overflow: hidden;}
.db-legend {display: flex; flex-wrap: wrap; gap: 6px 14px; font-size: .78rem; margin-top: 6px;}
.db-legend i {display: inline-block; width: 9px; height: 9px; border-radius: 50%; margin-right: 5px;}
.db-result {font-size: 1rem; padding: 10px 12px; border-radius: 12px; background: rgba(127,127,127,.10);}
.db-chips {display: flex; flex-wrap: wrap; gap: 6px; margin: 8px 0;}
.db-chip {font-size: .78rem; padding: 3px 10px; border-radius: 999px; background: rgba(16,185,129,.18);}
"""

MAX_QUICK = 6  # number of quick-reply buttons under the chat box


def quick_labels(state):
    """Return the labels of the quick-reply buttons for the current step."""
    step = state["step"]
    if step in CHOICES:
        return CHOICES[step]
    if step in ("allergies", "conditions"):
        return ["none"]
    if step == "chat":
        return ["show my plan", "results", "grocery list", "save", "help", "restart"]
    if step in ("ended", "blocked"):
        return ["restart"]
    return []


def ui_updates(state):
    """Return updates for: dashboard, the quick buttons, the tools row and the download box."""
    labels = quick_labels(state)
    buttons = []
    for i in range(MAX_QUICK):
        if i < len(labels):
            buttons.append(gr.update(value=labels[i], visible=True))
        else:
            buttons.append(gr.update(visible=False))
    has_file = state["file"] is not None
    return [dashboard_html(state), *buttons, gr.update(visible=state["step"] == "chat"),
            gr.update(value=state["file"], visible=has_file)]


# ------------------------------------------------------------------
# BUILDING THE GRADIO APP
# ------------------------------------------------------------------
def build_app():
    """Create the Gradio interface and connect the buttons to the chatbot brain."""
    theme = gr.themes.Soft(primary_hue="emerald", secondary_hue="teal", neutral_hue="slate")

    # Gradio 6 takes theme/css in launch(); older versions take them in Blocks()
    css_in_launch = "css" in inspect.signature(gr.Blocks.launch).parameters
    blocks_kwargs = {} if css_in_launch else {"theme": theme, "css": CSS}
    launch_kwargs = {"theme": theme, "css": CSS} if css_in_launch else {}

    chatbot_kwargs = {}
    if "type" in inspect.signature(gr.Chatbot.__init__).parameters:   # Gradio 4/5
        chatbot_kwargs["type"] = "messages"

    with gr.Blocks(title="DietBot - Diet Plan Generator", **blocks_kwargs) as demo:
        gr.HTML(HEADER_HTML)
        state = gr.State(new_state())

        with gr.Row(equal_height=False):
            with gr.Column(scale=3):
                chatbot = gr.Chatbot(
                    value=[{"role": "assistant", "content": greeting_text()}],
                    height=560, show_label=False, group_consecutive_messages=False,
                    **chatbot_kwargs)
                with gr.Row():
                    box = gr.Textbox(placeholder="Type your answer here and press Enter ✨",
                                     show_label=False, container=False, scale=6, autofocus=True)
                    send = gr.Button("Send ➤", variant="primary", scale=1)
                with gr.Row(elem_classes="quick-row"):
                    quick = [gr.Button("", visible=False, size="sm", elem_classes="quick-btn")
                             for _ in range(MAX_QUICK)]
                with gr.Row(visible=False) as tools:
                    day_box = gr.Dropdown([str(d) for d in range(1, 8)], value="1", label="Day", scale=1)
                    slot_box = gr.Dropdown(MEAL_SLOTS, value="dinner", label="Meal", scale=2)
                    show_btn = gr.Button("👁 Show day", scale=1)
                    swap_btn = gr.Button("🔄 Swap meal", scale=1)
                file_box = gr.File(label="📥 Your saved plan (diet_plan.txt)", visible=False)
            with gr.Column(scale=2):
                dashboard = gr.HTML(dashboard_html(new_state()))

        gr.Markdown("<center><small>⚠️ For general information only. Please consult a doctor or "
                    "registered dietitian before starting any diet.</small></center>")

        outputs = [chatbot, state, box, dashboard, *quick, tools, file_box]

        def respond(text, history, session):
            """Send one message through the brain and refresh every part of the screen."""
            history, session = handle_message(text, history, session)
            return [history, session, "", *ui_updates(session)]

        def make_quick_handler(index):
            """Return a click handler for quick button number 'index'."""
            def on_click(history, session):
                labels = quick_labels(session)
                text = labels[index] if index < len(labels) else ""
                return respond(text, history, session)
            return on_click

        box.submit(respond, [box, chatbot, state], outputs, api_name="chat")
        send.click(respond, [box, chatbot, state], outputs)
        for index, button in enumerate(quick):
            button.click(make_quick_handler(index), [chatbot, state], outputs)
        show_btn.click(lambda d, h, s: respond(f"show day {d}", h, s),
                       [day_box, chatbot, state], outputs)
        swap_btn.click(lambda d, m, h, s: respond(f"swap {m} for day {d}", h, s),
                       [day_box, slot_box, chatbot, state], outputs)

    return demo, launch_kwargs



if __name__ == "__main__":
    import os

    app, launch_options = build_app()

    # Remove options that may conflict with Render
    launch_options.pop("server_name", None)
    launch_options.pop("server_port", None)
    launch_options.pop("share", None)

    app.launch(
        **launch_options,
        server_name="0.0.0.0",
        server_port=int(os.environ.get("PORT", "10000")),
    )
