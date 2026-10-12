# ruff: noqa: N801 -- the annex-prefixed class names are the registry's
# contract (``XI_IntendedTasks``, ``XII_IntendedTasks``); the PEP 8
# class-name rule is waived for this module rather than renamed away.
"""The Annex XII element models.

Each of the eleven leaves is a ``RootModel[TextValue]`` whose title and
docstring carry the registry's id and label - ``ConfigDict`` has no typed
``description`` key - so the exported schema is self-describing;
:class:`AnnexXII` maps them in registry order, every one optional.
"""

from pydantic import ConfigDict, RootModel

from gpai_docs.models.leaves import Model, TextValue


class XII_IntendedTasks(RootModel[TextValue]):
    """Tasks the model is intended to perform"""

    model_config = ConfigDict(title="XII.1.a")


class XII_AcceptableUsePolicies(RootModel[TextValue]):
    """Acceptable use policies"""

    model_config = ConfigDict(title="XII.1.b")


class XII_ReleaseDateAndDistribution(RootModel[TextValue]):
    """Date of release and methods of distribution"""

    model_config = ConfigDict(title="XII.1.c")


class XII_HardwareSoftwareInteraction(RootModel[TextValue]):
    """Interaction with hardware or software"""

    model_config = ConfigDict(title="XII.1.d")


class XII_SoftwareVersions(RootModel[TextValue]):
    """Versions of relevant software"""

    model_config = ConfigDict(title="XII.1.e")


class XII_ArchitectureAndParameters(RootModel[TextValue]):
    """Architecture and number of parameters"""

    model_config = ConfigDict(title="XII.1.f")


class XII_InputOutputModalities(RootModel[TextValue]):
    """Modality and format of inputs and outputs"""

    model_config = ConfigDict(title="XII.1.g")


class XII_Licence(RootModel[TextValue]):
    """Licence for the model"""

    model_config = ConfigDict(title="XII.1.h")


class XII_TechnicalMeansForIntegration(RootModel[TextValue]):
    """Technical means for model integration"""

    model_config = ConfigDict(title="XII.2.a")


class XII_ModalitiesAndMaximumSize(RootModel[TextValue]):
    """Modality, format and maximum size of inputs and outputs"""

    model_config = ConfigDict(title="XII.2.b")


class XII_TrainingData(RootModel[TextValue]):
    """Data used for training, testing and validation"""

    model_config = ConfigDict(title="XII.2.c")


class AnnexXII(Model):
    """The Annex XII element values of one model document."""

    model_config = ConfigDict(extra="forbid", title="annex_xii")

    intended_tasks: XII_IntendedTasks | None = None
    acceptable_use_policies: XII_AcceptableUsePolicies | None = None
    release_date_and_distribution: XII_ReleaseDateAndDistribution | None = None
    hardware_software_interaction: XII_HardwareSoftwareInteraction | None = None
    software_versions: XII_SoftwareVersions | None = None
    architecture_and_parameters: XII_ArchitectureAndParameters | None = None
    input_output_modalities: XII_InputOutputModalities | None = None
    licence: XII_Licence | None = None
    technical_means_for_integration: XII_TechnicalMeansForIntegration | None = None
    modalities_and_maximum_size: XII_ModalitiesAndMaximumSize | None = None
    training_data: XII_TrainingData | None = None
