from pydantic import BaseModel
from typing import Optional


class QualificationSubmission(BaseModel):
    location_id: str
    contact_id: Optional[str] = None  # None means create a new contact

    # Contact basics (required when contact_id is None)
    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    state: Optional[str] = None
    age: Optional[int] = None
    sex_at_birth: Optional[str] = None
    occupation: Optional[str] = None
    height: Optional[str] = None
    weight: Optional[str] = None

    # Coverage goals
    product_type: Optional[str] = None
    coverage_amount: Optional[str] = None
    budget: Optional[str] = None
    urgency: Optional[str] = None
    goal: Optional[str] = None

    # Underwriting triage
    pending_tests: Optional[str] = None
    hospital_recent: Optional[str] = None
    underwriting_history: Optional[str] = None
    dui_history: Optional[str] = None
    sleep_apnea: bool = False
    cpap: bool = False
    diabetes_meds: bool = False
    psych_meds: bool = False
    inhaler: bool = False
    cardiac_history: bool = False

    # Medications
    med_list: Optional[str] = None
    med_change: Optional[str] = None

    # Existing coverage
    existing_coverage: Optional[str] = None
    prior_outcome: Optional[str] = None
    underwriting_notes: Optional[str] = None

    # Computed client-side before submission
    triage_state: Optional[str] = None       # clean | follow_up | elevated
    active_dependencies: Optional[str] = None  # comma-separated labels
    product_direction: Optional[str] = None
