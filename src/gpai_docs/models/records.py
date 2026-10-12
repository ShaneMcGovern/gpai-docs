"""The records sections' models.

Every subfield is optional: subfield requiredness and the cross-checks (the
two-week window, the one-third comparison) belong to the consistency pass, so
the format fixes only the names and value kinds. A ``provider_record`` states what
the document asserts about the modification, never a verdict of ours.
"""

from pydantic import ConfigDict

from gpai_docs.models.leaves import (
    BooleanValue,
    DateValue,
    Model,
    NumberValue,
    TextValue,
)


class NotificationRecord(Model):
    """One Art. 52(1) notification record: the compute that triggered the duty"""

    model_config = ConfigDict(extra="forbid", title="NotificationRecord")

    compute_flop: NumberValue | None = None
    estimation_method: TextValue | None = None
    aware_on: DateValue | None = None
    notified_on: DateValue | None = None


class ModificationRecord(Model):
    """One modification record: what was modified and the compute it used"""

    model_config = ConfigDict(extra="forbid", title="ModificationRecord")

    description: TextValue | None = None
    training_flop: NumberValue | None = None
    provider_record: BooleanValue | None = None
