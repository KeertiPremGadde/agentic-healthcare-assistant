"""Phrases for the "is this a general question or a live emergency?" decision (data, not tests).

A red-flag word in a message gets one of two treatments:
- INFORMATIONAL: a general question. It is answered, with the safety notice in front.
- the emergency reply: someone may be in danger now.

The rule when in doubt is to keep over-warning: a missed emergency costs more than an extra
safety notice. So GENUINE emergencies (first or third person, present tense, even when phrased
as a question) and AMBIGUOUS questions ("How do I know if it's a heart attack?", which a person
with symptoms asks) must keep the emergency reply; only clearly general questions flip.
"""

INFORMATIONAL_EN: list[str] = [
    "How can I recognise a stroke?",
    "How can I recognize the signs of a heart attack?",
    "How can I recognise self-harm in teenagers?",
    "How do I recognise anaphylaxis in children?",
    "How can I prevent a heart attack?",
    "How can I lower my risk of a stroke?",
    "How can I tell the difference between a stroke and a migraine?",
    "How can I recognise a stroke in my mother?",
    "How can I protect my children from choking on food?",
    "What should I know about the symptoms of a seizure?",
    "Hello! How can I recognise the warning signs of a heart attack?",
    "Hi, what are the warning signs of a heart attack?",
    "Who is at risk of a stroke?",
    "Where can I find information about suicide prevention?",
    "Could chest pain be a sign of anxiety?",
]
INFORMATIONAL_DE: list[str] = [
    "Wie erkenne ich einen Schlaganfall?",
    "Woran erkenne ich einen Herzinfarkt?",
    "Woran erkennt man Selbstverletzung bei Jugendlichen?",
    "Wie kann ich einem Herzinfarkt vorbeugen?",
    "Wie kann ich mein Risiko für einen Schlaganfall senken?",
    "Wie unterscheide ich einen Schlaganfall von einer Migräne?",
    "Wie erkenne ich einen Schlaganfall bei meiner Mutter?",
    "Wie schütze ich meine Kinder vor dem Ersticken?",
    "Wodurch entsteht ein Krampfanfall?",
    "Hallo, wie erkenne ich eine Alkoholvergiftung?",
    "Wo finde ich Informationen zu Suizidprävention?",
    "Wer hat ein erhöhtes Risiko für einen Schlaganfall?",
    "Welche Anzeichen hat ein Herzinfarkt bei Frauen?",
]

# Someone may be in danger now: these keep the emergency reply, question-shaped or not.
GENUINE_EN: list[str] = [
    # a second clause WITHOUT punctuation and with a verb no list would know
    "How can I recognise a stroke my husband slurs his words",
    "How can I recognise a stroke he cannot move his arm",
    "How can I recognise a stroke I feel numb on one side",
    "How can I recognise a stroke my wife went limp",
    # borderline: a knowledge question where exactly ONE guard keeps the emergency reply
    "How can I recognise a stroke when my husband is slurring his words",  # "happening now"
    "How can I recognise a stroke right now",  # "happening now"
    "How can I recognise a heart attack tonight",  # "happening now"
    "How can I recognise a stroke I think I am having one",  # "happening now"
    "How can I recognise a stroke? Please hurry",  # a second sentence
    "How can I recognise a stroke, quickly",  # a clause joined by a comma
    "I think I'm having a heart attack",
    "How do I know if I'm having a stroke? My face is drooping",
    "How can I recognise if my husband is having a stroke, his speech is slurred",
    "My husband has a stroke, what should I do?",
    "What should I do? My daughter can't breathe",
    "What do I do, he is unconscious",
    "How can I help? She is bleeding heavily",
    "Can you help me? I have crushing chest pain",
    "Is this a stroke? My mother's face is drooping",
    "What do I do if I want to kill myself",
    "How can I stop the bleeding, he is bleeding badly",
    "Hello, my son is having a seizure, how long will it last?",
    "How do I help my friend who is choking?",
    "I want to die",
]
GENUINE_DE: list[str] = [
    # a second clause WITHOUT punctuation and with a verb no list would know
    "Wie erkenne ich einen Schlaganfall mein Mann lallt und kann den Arm nicht heben",
    "Wie erkenne ich einen Schlaganfall er kann den Arm nicht heben",
    "Wie erkenne ich einen Schlaganfall meine Mutter kippt um",
    # borderline: a knowledge question where exactly ONE guard keeps the emergency reply
    "Wie erkenne ich einen Schlaganfall wenn mein Mann gerade lallt",  # "happening now"
    "Wie erkenne ich einen Schlaganfall ich glaube ich habe einen",  # a new subject
    "Wie erkenne ich einen Herzinfarkt gerade",  # "happening now"
    "Woran erkenne ich einen Schlaganfall jetzt",  # "happening now"
    "Wie erkenne ich einen Schlaganfall? Bitte schnell",  # a second sentence
    "Wie erkenne ich einen Schlaganfall, schnell bitte",  # a clause joined by a comma
    "Ich glaube, ich habe einen Herzinfarkt",
    "Wie erkenne ich, ob mein Mann einen Schlaganfall hat? Sein Mundwinkel hängt",
    "Woran erkenne ich, ob ich gerade einen Schlaganfall habe?",
    "Was soll ich tun, mein Kind bekommt keine Luft",
    "Hilfe, er ist bewusstlos, wie lange darf ich warten?",
    "Was mache ich, wenn ich nicht mehr leben will?",
    "Wie kann ich helfen, sie blutet stark",
    "Ist das ein Herzinfarkt? Ich habe starke Schmerzen in der Brust",
    "Ich möchte sterben",
]

# Questions a person with symptoms asks: kept as emergencies on purpose (over-warn when in doubt).
AMBIGUOUS_EN: list[str] = [
    "How do I know if it's a heart attack or heartburn?",
    "When should I worry about chest pain?",
    "What should I do if someone has a stroke?",
    "Should I call an ambulance for chest pain?",
    "Is chest pain after eating dangerous for me?",
    "What do I do about chest pain on stairs?",
]
AMBIGUOUS_DE: list[str] = [
    "Woher weiß ich, ob es ein Herzinfarkt ist?",
    "Soll ich bei Brustschmerzen den Notruf wählen?",
    "Was soll ich tun, wenn jemand einen Schlaganfall hat?",
    "Kann ich bei Brustschmerzen noch Sport machen?",
]
