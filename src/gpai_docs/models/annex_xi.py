# ruff: noqa: N801 -- the annex-prefixed class names are the registry's
# contract (``XI_IntendedTasks``, ``XII_IntendedTasks``); the PEP 8
# class-name rule is waived for this module rather than renamed away.
"""The Annex XI, Section 1 and Section 2 element models.

Fields are optional and ``extra="forbid"`` by design: presence and subfield
requiredness belong to the completeness and consistency passes, and each
docstring is the label pydantic emits as the schema description.
"""

from pydantic import ConfigDict, RootModel

from gpai_docs.models.leaves import Model, NumberValue, TextValue


class XI_IntendedTasks(RootModel[TextValue]):
    """Tasks the model is intended to perform"""

    model_config = ConfigDict(title="XI.1.1.a")


class XI_AcceptableUsePolicies(RootModel[TextValue]):
    """Acceptable use policies"""

    model_config = ConfigDict(title="XI.1.1.b")


class XI_ReleaseDateAndDistribution(RootModel[TextValue]):
    """Date of release and methods of distribution"""

    model_config = ConfigDict(title="XI.1.1.c")


class XI_ArchitectureAndParameters(RootModel[TextValue]):
    """Architecture and number of parameters"""

    model_config = ConfigDict(title="XI.1.1.d")


class XI_InputOutputModalities(RootModel[TextValue]):
    """Modality and format of inputs and outputs"""

    model_config = ConfigDict(title="XI.1.1.e")


class XI_Licence(RootModel[TextValue]):
    """Licence"""

    model_config = ConfigDict(title="XI.1.1.f")


class XI_TechnicalMeansForIntegration(RootModel[TextValue]):
    """Technical means for model integration"""

    model_config = ConfigDict(title="XI.1.2.a")


class XI_DesignSpecifications(RootModel[TextValue]):
    """Design specifications of the model and training process"""

    model_config = ConfigDict(title="XI.1.2.b")


class XI_TrainingData(RootModel[TextValue]):
    """Data used for training, testing and validation"""

    model_config = ConfigDict(title="XI.1.2.c")


class XI_EvaluationStrategies(RootModel[TextValue]):
    """Evaluation strategies"""

    model_config = ConfigDict(title="XI.2.1")


class XI_AdversarialTesting(RootModel[TextValue]):
    """Adversarial testing and model adaptations"""

    model_config = ConfigDict(title="XI.2.2")


class XI_SystemArchitecture(RootModel[TextValue]):
    """System architecture"""

    model_config = ConfigDict(title="XI.2.3")


class ComputationalResources(Model):
    """Computational resources used to train the model"""

    model_config = ConfigDict(extra="forbid", title="XI.1.2.d")

    training_flop: NumberValue | None = None
    estimation_method: TextValue | None = None
    training_time: TextValue | None = None


class EnergyTraining(Model):
    """The training arm of the energy element: an amount in its reported unit"""

    model_config = ConfigDict(
        extra="forbid", title="annex_xi.energy_consumption.training"
    )

    amount: NumberValue | None = None
    unit: TextValue | None = None
    method: TextValue | None = None


class EnergyInference(Model):
    """The inference arm of the energy element: an amount in its reported unit"""

    model_config = ConfigDict(
        extra="forbid", title="annex_xi.energy_consumption.inference"
    )

    amount: NumberValue | None = None
    unit: TextValue | None = None
    method: TextValue | None = None


class EnergyConsumption(Model):
    """Energy consumption"""

    model_config = ConfigDict(extra="forbid", title="XI.1.2.e")

    training: EnergyTraining | None = None
    inference: EnergyInference | None = None


class AnnexXI(Model):
    """The Annex XI, Section 1 and Section 2 element values of one model document."""

    model_config = ConfigDict(extra="forbid", title="annex_xi")

    intended_tasks: XI_IntendedTasks | None = None
    acceptable_use_policies: XI_AcceptableUsePolicies | None = None
    release_date_and_distribution: XI_ReleaseDateAndDistribution | None = None
    architecture_and_parameters: XI_ArchitectureAndParameters | None = None
    input_output_modalities: XI_InputOutputModalities | None = None
    licence: XI_Licence | None = None
    technical_means_for_integration: XI_TechnicalMeansForIntegration | None = None
    design_specifications: XI_DesignSpecifications | None = None
    training_data: XI_TrainingData | None = None
    computational_resources: ComputationalResources | None = None
    energy_consumption: EnergyConsumption | None = None
    evaluation_strategies: XI_EvaluationStrategies | None = None
    adversarial_testing: XI_AdversarialTesting | None = None
    system_architecture: XI_SystemArchitecture | None = None
