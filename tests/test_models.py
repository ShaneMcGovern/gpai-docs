"""The v0.1 document models' accepted-shape value matrix.

Every value is exercised through the same pydantic types the lint pass
validates with, so the format's shape rules are pinned where they are
implemented. The registry lockstep lives in tests/test_lockstep.py.
"""

import datetime

import pytest
import yaml
from pydantic import RootModel, TypeAdapter, ValidationError

from gpai_docs.models import (
    DateValue,
    ModelDocument,
    ModificationRecord,
    NotificationRecord,
    NumberValue,
    TextListValue,
    TextValue,
    UrlValue,
)
from gpai_docs.models.annex_xi import (
    AnnexXI,
    ComputationalResources,
    EnergyConsumption,
    EnergyTraining,
    XI_AdversarialTesting,
    XI_EvaluationStrategies,
    XI_Licence,
    XI_SystemArchitecture,
)
from gpai_docs.models.annex_xii import (
    AnnexXII,
    XII_AcceptableUsePolicies,
    XII_ArchitectureAndParameters,
    XII_HardwareSoftwareInteraction,
    XII_InputOutputModalities,
    XII_IntendedTasks,
    XII_Licence,
    XII_ModalitiesAndMaximumSize,
    XII_ReleaseDateAndDistribution,
    XII_SoftwareVersions,
    XII_TechnicalMeansForIntegration,
    XII_TrainingData,
)

TEXT = TypeAdapter(TextValue)
TEXT_LIST = TypeAdapter(TextListValue)
NUMBER = TypeAdapter(NumberValue)
DATE = TypeAdapter(DateValue)
URL = TypeAdapter(UrlValue)


@pytest.mark.parametrize("value", ["x", ""])
def test_text_value_accepts_strings_including_the_empty_one(value: str) -> None:
    # The empty string is present-but-empty: completeness' business, not the
    # format's. Only a non-string is malformed.
    assert TEXT.validate_python(value) == value


@pytest.mark.parametrize("value", [5, ["x"], True, b"x", None])
def test_text_value_rejects_every_non_string(value: object) -> None:
    with pytest.raises(ValidationError):
        TEXT.validate_python(value)


@pytest.mark.parametrize("value", [["a", "b"], []])
def test_text_list_value_accepts_lists_of_non_empty_strings(value: list[str]) -> None:
    assert TEXT_LIST.validate_python(value) == value


@pytest.mark.parametrize("value", [["a", ""], "a", [5], [None], None])
def test_text_list_value_rejects_bad_entries_and_non_lists(value: object) -> None:
    with pytest.raises(ValidationError):
        TEXT_LIST.validate_python(value)


def test_number_value_accepts_numbers_and_keeps_them_exact() -> None:
    assert NUMBER.validate_python(1) == 1
    validated = NUMBER.validate_python(2.3e25)
    assert isinstance(validated, float)
    assert validated == 2.3e25


@pytest.mark.parametrize("value", [True, "2.3", "2"])
def test_number_value_rejects_booleans_and_strings(value: object) -> None:
    # A before-validator refuses these ahead of pydantic's lax coercion, which
    # would otherwise read True as 1 and "2.3" as 2.3.
    with pytest.raises(ValidationError):
        NUMBER.validate_python(value)


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_number_value_rejects_non_finite_floats(value: float) -> None:
    with pytest.raises(ValidationError):
        NUMBER.validate_python(value)


@pytest.mark.parametrize("value", [b"23e25", bytearray(b"1")])
def test_number_value_rejects_byte_strings(value: bytes | bytearray) -> None:
    # YAML's !!binary tag decodes to bytes, and pydantic's lax mode would
    # read b"23e25" as 2.3e+26; the guard refuses the bytes themselves.
    with pytest.raises(ValidationError):
        NUMBER.validate_python(value)


def test_a_yaml_binary_value_never_becomes_a_number() -> None:
    # The same refusal end to end: the loader's reader hands the model the
    # bytes the tag produced, and validation refuses them.
    raw = yaml.safe_load(
        "schema: 1\nnotifications:\n  - compute_flop: !!binary MjNlMjU=\n"
    )
    assert raw["notifications"][0]["compute_flop"] == b"23e25"
    with pytest.raises(ValidationError):
        ModelDocument.model_validate(raw)


def test_date_value_accepts_dates_and_exact_iso_strings() -> None:
    day = datetime.date(2026, 7, 20)
    assert DATE.validate_python(day) == day
    assert DATE.validate_python("2026-07-20") == day


@pytest.mark.parametrize(
    "value",
    ["2026-7-2", "2026-13-01", "2026-07-20T00:00:00", 5],
)
def test_date_value_rejects_everything_but_a_date_or_iso_string(
    value: object,
) -> None:
    with pytest.raises(ValidationError):
        DATE.validate_python(value)


def test_date_value_refuses_a_datetime_even_though_it_subclasses_date() -> None:
    # datetime is a date subclass; accepting one would silently truncate the
    # time, so the check must name the type it refuses.
    with pytest.raises(ValidationError, match="datetime is not a date"):
        DATE.validate_python(datetime.datetime(2026, 7, 20, 10, 0))


def test_url_value_accepts_http_and_https() -> None:
    assert URL.validate_python("https://example.org/x") == "https://example.org/x"
    assert URL.validate_python("http://example.org") == "http://example.org"


@pytest.mark.parametrize(
    "value", ["ftp://example.org", "example.org", "https://", "https:///path"]
)
def test_url_value_rejects_non_http_schemes_and_missing_hosts(value: str) -> None:
    with pytest.raises(ValidationError):
        URL.validate_python(value)


def test_a_notification_record_validates_with_every_subfield_absent() -> None:
    record = NotificationRecord()
    assert record.compute_flop is None
    assert record.estimation_method is None
    assert record.aware_on is None
    assert record.notified_on is None


def test_a_notification_record_accepts_the_typed_subfields() -> None:
    record = NotificationRecord.model_validate(
        {
            "compute_flop": 2.3e25,
            "estimation_method": "hardware-day extrapolation",
            "aware_on": "2026-07-20",
            "notified_on": datetime.date(2026, 7, 30),
        }
    )
    assert record.compute_flop == 2.3e25
    assert record.aware_on == datetime.date(2026, 7, 20)
    assert record.notified_on == datetime.date(2026, 7, 30)


def test_a_notification_record_rejects_an_unknown_key_naming_it() -> None:
    with pytest.raises(ValidationError) as caught:
        NotificationRecord.model_validate({"notified_at": "2026-07-20"})
    error = caught.value.errors()[0]
    assert error["type"] == "extra_forbidden"
    assert error["loc"] == ("notified_at",)


def test_a_modification_record_validates_with_every_subfield_absent() -> None:
    record = ModificationRecord()
    assert record.description is None
    assert record.training_flop is None
    assert record.provider_record is None


def test_a_modification_record_accepts_the_typed_subfields() -> None:
    record = ModificationRecord.model_validate(
        {
            "description": "continued pre-training",
            "training_flop": 9.0e24,
            "provider_record": True,
        }
    )
    assert record.training_flop == 9.0e24
    assert record.provider_record is True


def test_a_modification_record_rejects_an_unknown_key_naming_it() -> None:
    with pytest.raises(ValidationError) as caught:
        ModificationRecord.model_validate({"training_flops": 9.0e24})
    error = caught.value.errors()[0]
    assert error["type"] == "extra_forbidden"
    assert error["loc"] == ("training_flops",)


@pytest.mark.parametrize("value", [True, False, None])
def test_provider_record_accepts_only_a_real_boolean(value: bool | None) -> None:
    record = ModificationRecord.model_validate({"provider_record": value})
    assert record.provider_record is value


@pytest.mark.parametrize("value", ["true", 1, 0, b"1"])
def test_provider_record_refuses_a_coerced_boolean(value: object) -> None:
    # A quoted "true" and a number in the boolean slot are malformed, not
    # booleans to coerce: the document's assertion must be a real one.
    with pytest.raises(ValidationError):
        ModificationRecord.model_validate({"provider_record": value})


XII_LEAVES: list[type[RootModel[str]]] = [
    XII_IntendedTasks,
    XII_AcceptableUsePolicies,
    XII_ReleaseDateAndDistribution,
    XII_HardwareSoftwareInteraction,
    XII_SoftwareVersions,
    XII_ArchitectureAndParameters,
    XII_InputOutputModalities,
    XII_Licence,
    XII_TechnicalMeansForIntegration,
    XII_ModalitiesAndMaximumSize,
    XII_TrainingData,
]


@pytest.mark.parametrize("leaf", XII_LEAVES)
def test_every_xii_leaf_validates_a_text_value(leaf: type[RootModel[str]]) -> None:
    assert leaf.model_validate("the element's text").root == "the element's text"
    with pytest.raises(ValidationError):
        leaf.model_validate(5)


def test_the_xii_licence_carries_its_registry_id_and_label() -> None:
    # The id is read from fields.yaml; XII.1.h is "Licence for the model",
    # not bare "Licence" (that is XI.1.1.f).
    schema = XII_Licence.model_json_schema()
    assert schema["title"] == "XII.1.h"
    assert schema["description"] == "Licence for the model"


def test_the_xi_licence_carries_its_registry_id_and_label() -> None:
    schema = XI_Licence.model_json_schema()
    assert schema["title"] == "XI.1.1.f"
    assert schema["description"] == "Licence"


XI_SECTION_2_LEAVES: list[type[RootModel[str]]] = [
    XI_EvaluationStrategies,
    XI_AdversarialTesting,
    XI_SystemArchitecture,
]


@pytest.mark.parametrize("leaf", XI_SECTION_2_LEAVES)
def test_every_section_2_leaf_validates_a_text_value(
    leaf: type[RootModel[str]],
) -> None:
    assert leaf.model_validate("the element's text").root == "the element's text"
    with pytest.raises(ValidationError):
        leaf.model_validate(5)


def test_a_section_2_leaf_carries_its_registry_id_and_label() -> None:
    schema = XI_EvaluationStrategies.model_json_schema()
    assert schema["title"] == "XI.2.1"
    assert schema["description"] == "Evaluation strategies"


def test_an_empty_annex_xi_validates_with_every_element_absent() -> None:
    section = AnnexXI()
    assert section.intended_tasks is None
    assert section.acceptable_use_policies is None
    assert section.computational_resources is None
    assert section.energy_consumption is None
    assert section.evaluation_strategies is None
    assert section.adversarial_testing is None
    assert section.system_architecture is None


def test_annex_xi_validates_the_section_2_leaf_values() -> None:
    section = AnnexXI.model_validate(
        {
            "evaluation_strategies": "Public benchmarks and a limitation review.",
            "adversarial_testing": "An external red-team exercise, where applicable.",
            "system_architecture": "Where applicable, the component diagram.",
        }
    )
    assert section.evaluation_strategies is not None
    assert section.evaluation_strategies.root == (
        "Public benchmarks and a limitation review."
    )
    assert section.adversarial_testing is not None
    assert section.system_architecture is not None


def test_annex_xi_rejects_a_key_that_is_not_an_element() -> None:
    with pytest.raises(ValidationError) as caught:
        AnnexXI.model_validate({"computational_resource": {"training_flop": 1}})
    error = caught.value.errors()[0]
    assert error["type"] == "extra_forbidden"
    assert error["loc"] == ("computational_resource",)


def test_computational_resources_validates_its_typed_subfields() -> None:
    element = ComputationalResources(
        training_flop=2.3e25, estimation_method="hardware extrapolation"
    )
    assert element.training_flop == 2.3e25
    assert element.estimation_method == "hardware extrapolation"
    assert element.training_time is None


def test_computational_resources_rejects_a_text_training_flop() -> None:
    with pytest.raises(ValidationError):
        ComputationalResources.model_validate({"training_flop": "big"})


def test_computational_resources_rejects_an_unknown_subfield() -> None:
    with pytest.raises(ValidationError, match="training_flops"):
        ComputationalResources.model_validate({"training_flops": 2.3e25})


def test_the_compute_element_carries_its_registry_id() -> None:
    assert ComputationalResources.model_json_schema()["title"] == "XI.1.2.d"


def test_energy_consumption_nests_training_and_inference() -> None:
    element = EnergyConsumption(training=EnergyTraining(amount=1200, unit="MWh"))
    assert element.training is not None
    assert element.training.amount == 1200
    assert element.training.unit == "MWh"
    assert element.training.method is None
    assert element.inference is None


def test_energy_subfields_keep_their_text_and_number_kinds() -> None:
    with pytest.raises(ValidationError):
        EnergyTraining.model_validate({"amount": 1200, "unit": 7})
    with pytest.raises(ValidationError):
        EnergyTraining.model_validate({"amount": "a lot"})


def test_the_energy_element_carries_its_registry_id() -> None:
    assert EnergyConsumption.model_json_schema()["title"] == "XI.1.2.e"


def test_an_empty_annex_xii_validates_with_every_element_absent() -> None:
    section = AnnexXII()
    assert section.licence is None
    assert section.training_data is None


def test_annex_xii_validates_its_leaf_values() -> None:
    section = AnnexXII.model_validate(
        {"licence": "MIT", "intended_tasks": "serve a website"}
    )
    assert section.licence is not None
    assert section.licence.root == "MIT"


def test_annex_xii_rejects_a_key_that_is_not_an_element() -> None:
    with pytest.raises(ValidationError) as caught:
        AnnexXII.model_validate({"hardware_software_interactions": "x"})
    error = caught.value.errors()[0]
    assert error["type"] == "extra_forbidden"
    assert error["loc"] == ("hardware_software_interactions",)


def test_model_document_validates_the_full_v0_1_shape() -> None:
    document = ModelDocument.model_validate(
        {
            "schema": 1,
            "annex_xi": {
                "intended_tasks": "answer questions",
                "computational_resources": {
                    "training_flop": 2.3e25,
                    "estimation_method": "hardware extrapolation",
                },
                "energy_consumption": {"training": {"amount": 1200, "unit": "MWh"}},
            },
            "annex_xii": {"licence": "MIT"},
            "notifications": [{"compute_flop": 2.3e25, "aware_on": "2026-07-20"}],
            "modifications": [
                {"description": "toxicity fine-tune", "provider_record": True}
            ],
        }
    )
    assert document.schema_ == 1
    assert document.systemic_risk is False
    assert document.annex_xi is not None
    assert document.annex_xi.computational_resources is not None
    assert document.annex_xi.computational_resources.training_flop == 2.3e25
    assert document.notifications[0].aware_on == datetime.date(2026, 7, 20)
    assert document.modifications[0].provider_record is True


def test_model_document_validates_with_only_the_marker() -> None:
    document = ModelDocument.model_validate({"schema": 1})
    assert document.annex_xi is None
    assert document.annex_xii is None
    assert document.notifications == []
    assert document.modifications == []


@pytest.mark.parametrize("value", [True, False])
def test_the_systemic_risk_marker_takes_a_real_boolean(value: bool) -> None:
    document = ModelDocument.model_validate({"schema": 1, "systemic_risk": value})
    assert document.systemic_risk is value


def test_the_systemic_risk_marker_is_absent_means_false() -> None:
    # The marker is optional within schema 1: a document without it
    # reads as a model without systemic risk.
    assert ModelDocument.model_validate({"schema": 1}).systemic_risk is False


@pytest.mark.parametrize("value", ["true", "yes", 1, 0, [True], b"1", None])
def test_the_systemic_risk_marker_refuses_a_coerced_boolean(value: object) -> None:
    # A quoted "true", a number, a null or a list in the marker slot is
    # malformed, not a boolean to coerce: the document's assertion must be a
    # real one.
    with pytest.raises(ValidationError):
        ModelDocument.model_validate({"schema": 1, "systemic_risk": value})


def test_model_document_takes_the_marker_under_its_format_key() -> None:
    # The field is aliased: the format's key is "schema" (that is the path the
    # lint pass pops and reinserts), and populate_by_name also admits the
    # Python name for construction in code. The exported schema keeps the
    # format's key.
    assert ModelDocument.model_validate({"schema": 1}).schema_ == 1
    assert ModelDocument.model_validate({"schema_": 1}).schema_ == 1
    assert "schema" in ModelDocument.model_json_schema()["properties"]


def test_model_document_requires_the_schema_marker() -> None:
    # The loader owns the marker's structural rule (exit 2 for a missing or
    # wrong version); the model declares it required all the same, so a
    # document validates whole or not at all. The lint pass pops the marker
    # from the raw values, so it must put the version it trusts back in.
    with pytest.raises(ValidationError) as caught:
        ModelDocument.model_validate({})
    error = caught.value.errors()[0]
    assert error["type"] == "missing"
    assert error["loc"] == ("schema",)


def test_model_document_refuses_a_marker_other_than_one() -> None:
    with pytest.raises(ValidationError):
        ModelDocument.model_validate({"schema": 2})


def test_model_document_rejects_an_unknown_top_level_key() -> None:
    with pytest.raises(ValidationError) as caught:
        ModelDocument.model_validate({"schema": 1, "annex_xi2": {}})
    error = caught.value.errors()[0]
    assert error["type"] == "extra_forbidden"
    assert error["loc"] == ("annex_xi2",)


def test_an_unknown_subfield_below_an_element_keeps_its_full_path() -> None:
    # The lint pass builds the unknown-key finding from this path, so a typo
    # inside a structured element is never dropped silently.
    with pytest.raises(ValidationError) as caught:
        ModelDocument.model_validate(
            {
                "schema": 1,
                "annex_xi": {"computational_resources": {"training_flops": 1}},
            }
        )
    error = caught.value.errors()[0]
    assert error["type"] == "extra_forbidden"
    assert error["loc"] == ("annex_xi", "computational_resources", "training_flops")


def test_the_package_exports_the_declared_surface() -> None:
    from gpai_docs import models

    assert set(models.__all__) == {
        "DateValue",
        "ModelDocument",
        "ModificationRecord",
        "NotificationRecord",
        "NumberValue",
        "TextListValue",
        "TextValue",
        "UrlValue",
    }
