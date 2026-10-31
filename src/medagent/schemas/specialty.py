"""The specialties the clinic offers. One source of truth for the seed data, the database
values and the LLM router's output schema (an enum, so the model can't invent a specialty)."""

import enum


class Specialty(enum.StrEnum):
    # Order matters: the deterministic seed assigns specialties round-robin in this order.
    GENERAL_PHYSICIAN = "General Physician"
    ENT_SPECIALIST = "ENT Specialist"
    CARDIOLOGIST = "Cardiologist"
    DERMATOLOGIST = "Dermatologist"
    ORTHOPEDIC = "Orthopedic"
    NEUROLOGIST = "Neurologist"
    DENTIST = "Dentist"
    PEDIATRICIAN = "Pediatrician"
    GYNECOLOGIST = "Gynecologist"
    OPHTHALMOLOGIST = "Ophthalmologist"
    UROLOGIST = "Urologist"
    PSYCHIATRIST = "Psychiatrist"
    ENDOCRINOLOGIST = "Endocrinologist"
    GASTROENTEROLOGIST = "Gastroenterologist"
    PULMONOLOGIST = "Pulmonologist"
    ONCOLOGIST = "Oncologist"
    RHEUMATOLOGIST = "Rheumatologist"
    NEPHROLOGIST = "Nephrologist"
    ALLERGIST = "Allergist"
