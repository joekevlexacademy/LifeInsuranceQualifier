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
    goal: Optional[str] = None  # primary reason for coverage → LIQ Coverage Reason

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

    # Dependency: Pending work-up
    pending_reason: Optional[str] = None
    pending_date: Optional[str] = None
    pending_doctor: Optional[str] = None
    pending_followup: Optional[str] = None
    pending_notes: Optional[str] = None

    # Dependency: Sleep apnea
    apnea_type: Optional[str] = None
    apnea_severity: Optional[str] = None
    ahi: Optional[str] = None
    cpap_use: Optional[str] = None
    nights_per_week: Optional[str] = None
    hours_per_night: Optional[str] = None
    daytime_fatigue: Optional[str] = None
    oxygen_night: Optional[str] = None
    apnea_conditions: Optional[str] = None  # comma-separated

    # Dependency: Diabetes
    diabetes_type: Optional[str] = None
    diagnosis_age: Optional[str] = None
    a1c: Optional[str] = None
    insulin_use: Optional[str] = None
    diabetes_control: Optional[str] = None
    diabetes_complications: Optional[str] = None  # comma-separated

    # Dependency: Mental health
    mh_diagnosis: Optional[str] = None
    mh_stability: Optional[str] = None
    therapy: Optional[str] = None
    mh_hospital: Optional[str] = None
    mh_notes: Optional[str] = None

    # Dependency: Respiratory
    resp_diagnosis: Optional[str] = None
    rescue_use: Optional[str] = None
    oral_steroids: Optional[str] = None
    smoker_status: Optional[str] = None
    resp_hospital: Optional[str] = None

    # Dependency: DUI / driving
    dui_count: Optional[str] = None
    dui_date: Optional[str] = None
    license_status: Optional[str] = None
    substance_program: Optional[str] = None
    bac: Optional[str] = None

    # Computed client-side before submission
    triage_state: Optional[str] = None        # clean | follow_up | elevated
    active_dependencies: Optional[str] = None  # comma-separated labels
    product_direction: Optional[str] = None
