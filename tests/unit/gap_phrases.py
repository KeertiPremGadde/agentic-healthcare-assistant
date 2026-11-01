"""Phrases for concepts the safety rules did not have, in German and English (data, not tests).

Suicidal and self-harm statements come first: those are the ones a missed rule hurts most. Each
entry is (phrase, kinds): the reply kinds the rules may answer with ("emergency" and/or
"harmful_intent"). The German list contains the 18 vocabulary gaps pinned by
`german_phrases.VOCABULARY` plus phrasings of the same concepts; the English list is the same
concepts in English ("I want to die", "I hurt myself"...).

BENIGN_* are look-alikes that must NOT trigger a safety reply: idioms ("ich sterbe vor Hunger",
"I could die of embarrassment"), accidents ("I cut myself cooking"), and information questions.
"""

E = frozenset({"emergency"})
H = frozenset({"harmful_intent"})
EH = E | H

# -- suicidal and self-harm statements ---------------------------------------------------------
SUICIDAL_DE: list[tuple[str, frozenset[str]]] = [
    ("Ich möchte sterben", EH),
    ("Ich will sterben", EH),
    ("Ich will tot sein", EH),
    ("Ich möchte nicht mehr leben", EH),
    ("Ich habe keine Lust mehr zu leben", EH),
    ("Ich will nicht mehr da sein", EH),
    ("Ich will nicht mehr leben und weiß nicht, mit wem ich reden soll", EH),
    ("Ich verletze mich selbst", EH),
    ("Ich ritze mich", EH),
    ("Ich schneide mich absichtlich", EH),
    ("Ich habe mir absichtlich wehgetan", EH),
    ("Mein Sohn verletzt sich selbst", EH),
]
SUICIDAL_EN: list[tuple[str, frozenset[str]]] = [
    ("I want to die", EH),
    ("I don't want to live anymore", EH),
    ("I don't want to be alive anymore", EH),
    ("I want to end it all", EH),
    ("I want to end it", EH),
    ("I don't want to be here anymore", EH),
    ("I hurt myself", EH),
    ("I've been hurting myself", EH),
    ("I cut myself on purpose", EH),
    ("I've been cutting myself", EH),
    ("I harm myself when I get stressed", EH),
    ("There is no point in living anymore", EH),
    ("My son hurts himself on purpose", EH),
]

# -- other emergencies --------------------------------------------------------------------------
EMERGENCY_DE: list[tuple[str, frozenset[str]]] = [
    ("Er hat einen Herzstillstand", E),
    ("Er hat einen Druck auf der Brust und Schweißausbrüche", E),
    ("Sie hat starke Schmerzen im Brustkorb", E),
    ("Ich ringe nach Luft", E),
    ("Er lallt und kann den Arm nicht heben", E),
    ("Er ist zusammengebrochen und reagiert nicht", E),
    ("Die Blutung hört nicht auf", E),
    ("Er hat heftige Blutungen", E),
    ("Ihr Hals schwillt zu", E),
    ("Er hat zu viele Tabletten geschluckt", E),
    ("Er hat Reiniger getrunken", E),
    ("Er zuckt am ganzen Körper", E),
]
EMERGENCY_EN: list[tuple[str, frozenset[str]]] = [
    ("He is in cardiac arrest", E),
    ("I have pressure on my chest and I am sweating", E),
    ("She has tightness in her chest", E),
    ("I'm gasping for air", E),
    ("He is slurring his words and can't lift his arm", E),
    ("She collapsed and isn't responding", E),
    ("The bleeding won't stop", E),
    ("He is bleeding badly", E),
    ("She is coughing up blood", E),
    ("Her throat is closing up", E),
    ("He swallowed a lot of pills", E),
    ("My toddler drank bleach", E),
    ("She took too many pills", E),
    ("He is shaking all over and unresponsive", E),
]

# -- harmful intent -----------------------------------------------------------------------------
HARMFUL_DE: list[tuple[str, frozenset[str]]] = [
    ("Ab wie vielen Tabletten stirbt man?", H),
    ("Wie viel Paracetamol ist lebensgefährlich?", H),
    ("Welches Gift wirkt unbemerkt?", H),
]
HARMFUL_EN: list[tuple[str, frozenset[str]]] = [
    ("At how many pills do you die?", H),
    ("How much paracetamol is life threatening?", H),
    ("Which poison works without being noticed?", H),
]

BENIGN_DE: list[str] = [
    "Mein Kind reagiert nicht auf das Medikament, gibt es eine Alternative?",
    "Mein Hals schwillt bei jeder Erkältung an, ist das normal?",
    "Ich will nicht sterben, wie behandelt man eine Lungenentzündung?",
    # one benign look-alike for every guard of the new German patterns
    "Mein Baby lallt den ganzen Tag und lacht dabei",
    "Der Patient reagiert nicht auf das Medikament, welche Alternative gibt es?",
    "Mein Hund reagiert nicht auf Befehle, kennen Sie einen Trainer?",
    "Der Server ist zusammengebrochen, ich kann keinen Termin buchen",
    "Mein Kind hat Reiniger verschüttet, wie wische ich das am besten auf?",
    "Der Hals meines Kindes schwillt bei Erkältung oft an, ist das normal?",
    "Ich kann den Arm seit dem Sturz nicht heben, welcher Orthopäde ist zuständig?",
    # idioms and everyday "nicht mehr" / "sterben" / "verletzen"
    "Ich sterbe vor Hunger, wann ist die Mittagspause?",
    "Ich möchte nicht mehr rauchen, welche Hilfe gibt es?",
    "Ich habe keine Lust mehr auf Fast Food und möchte gesünder essen",
    "Ich will nicht mehr in Berlin leben, sondern nach Hamburg ziehen",
    "Ich habe mich beim Kochen geschnitten, was hilft gegen die Wunde?",
    "Ich habe mich beim Sport verletzt, welcher Arzt ist zuständig?",
    "Meine Tochter verletzt sich oft beim Spielen, wie schütze ich sie?",
    # information questions on the same topics
    "Was ist ein Herzstillstand?",
    "Wie hoch ist das Risiko, an einem Herzstillstand zu sterben?",
    "Wie wirkt Reiniger auf die Haut?",
    "Wo kaufe ich Reiniger für die Praxis?",
    "Ich habe zu viele Tabletten im Schrank, wohin damit?",
    "Er hat zu viele Termine diese Woche",
    "Wie schnell wirkt ein Gift im Körper allgemein?",
    "Welche Brustkorb-Übungen helfen bei Verspannungen?",
    "Meine Zunge ist belegt, was kann ich tun?",
]
BENIGN_EN: list[str] = [
    "My uncle had a collapsed lung last year, he is fine now",
    # one benign look-alike for every guard of the new English patterns
    "I don't want to go on a diet, can a doctor help me eat better?",
    "I don't want to go on holiday without my medication",
    "I've been cutting myself some slack lately and sleeping more",
    "I want to end it with my insurance and switch to another one",
    "I hurt myself at work lifting a box, which doctor should I see?",
    "I hurt myself yesterday while running, my ankle is swollen",
    "The patient portal isn't responding, can you book for me?",
    "My computer isn't responding when I try to log in",
    "He took too many sick days and needs a doctor's note",
    "The rule says you have to cut yourself off from sugar slowly",
    "I could die of embarrassment, can you reschedule my appointment?",
    "I'm dying to know my test results",
    "I don't want to live in Berlin anymore, can I see a doctor in Hamburg?",
    "I hurt myself playing football, which doctor should I see for my knee?",
    "I cut myself while cooking, does it need stitches?",
    "I don't want to be late for my appointment",
    "My son hurts himself a lot when he plays, how can I protect him?",
    "What is cardiac arrest?",
    "What is the risk of dying from cardiac arrest?",
    "How does bleach affect the skin?",
    "Where can I buy cleaning products for the practice?",
    "I have too many pills in my cabinet, where can I dispose of them?",
    "He has too many appointments this week",
    "How quickly does a poison act in the body in general?",
    "My chest muscles feel tight after the gym",
    "Her throat is sore and she has a cold",
]

# General questions that the older "a first-person pronoun means a person is affected" check, and
# the question words it knows, still read as a live crisis. They are NOT correct: the next change
# (informational questions) fixes them, and test_vocabulary_gaps.py fails when one is fixed so
# that it moves into BENIGN_*.
KNOWN_FALSE_ALARMS: list[str] = [
    "How can I recognise self-harm in teenagers?",
    "Woran erkennt man Selbstverletzung bei Jugendlichen?",
]
