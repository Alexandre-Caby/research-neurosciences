import os

_ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
TOPIC = os.path.basename(_ROOT_DIR).replace("research-", "")

STORAGE_DIR = os.path.join(_ROOT_DIR, "storage")
RAW_DIR = os.path.join(STORAGE_DIR, "1_raw_data")
REGISTRY_DIR = os.path.join(STORAGE_DIR, "2_register_data")
EXP_DIR = os.path.join(STORAGE_DIR, "3_exploitable_data")
VECTOR_DIR = os.path.join(STORAGE_DIR, "4_vector_data")

DB_PATH = os.path.join(REGISTRY_DIR, f"{TOPIC}_registry.db")
LANCE_DIR = os.path.join(VECTOR_DIR, "lance")

def ensure_storage_dirs() -> None:
    for path in (STORAGE_DIR, RAW_DIR, REGISTRY_DIR, EXP_DIR, VECTOR_DIR, LANCE_DIR):
        os.makedirs(path, exist_ok=True)

ensure_storage_dirs()

EMAIL_CONTACT = os.environ.get("NEURO_CONTACT_EMAIL", "research@example.org")
CORE_API_KEY = os.environ.get("CORE_API_KEY", "")
HF_TOKEN = os.environ.get("HF_TOKEN", "")

TEXT_MODEL = "BAAI/bge-m3"
TEXT_DIM = 1024
EMBED_BATCH = 64

QUALITY_THRESHOLD = 0.6

CHUNK_SIZE_WORDS = 180
CHUNK_OVERLAP_WORDS = 30
MIN_TRAILING_CHUNK_WORDS = 20


def device() -> str:
    import torch
    return "cuda" if torch.cuda.is_available() else "cpu"


_NEURO_ANCHOR = '("brain" OR "neural" OR "cortex" OR "neuroscience" OR "nervous system")'

KEYWORD_BLOCKS: dict[str, str] = {
    "cognitive": (
        '("attention" OR "working memory" OR "episodic memory" OR "decision making" '
        'OR "cognitive control" OR "executive function" OR "learning" OR "consciousness") '
        f'AND {_NEURO_ANCHOR}'
    ),
    "systems_circuits": (
        '("neural circuit" OR "neural circuits" OR "sensory processing" OR "motor control" '
        'OR "connectome" OR "connectomics" OR "circuit dynamics") '
        f'AND {_NEURO_ANCHOR}'
    ),
    "molecular_cellular": (
        '("synaptic plasticity" OR "neurotransmitter" OR "ion channel" OR "neuronal signaling" '
        'OR "synapse" OR "dendrite" OR "axon guidance") '
        f'AND {_NEURO_ANCHOR}'
    ),
    "computational": (
        '("neural modeling" OR "spiking neural network" OR "neural coding" OR "neural dynamics" '
        'OR "computational neuroscience" OR "neural network model") '
        f'AND {_NEURO_ANCHOR}'
    ),
    "neuroimaging": (
        '("fMRI" OR "functional MRI" OR "PET imaging" OR "MEG" OR "diffusion tensor imaging" '
        'OR "DTI" OR "functional connectivity" OR "resting state") '
        f'AND {_NEURO_ANCHOR}'
    ),
    "clinical_neurology": (
        '("stroke" OR "traumatic brain injury" OR "TBI" OR "epilepsy" OR "multiple sclerosis" '
        'OR "neuroinflammation" OR "neurological disorder") '
        f'AND {_NEURO_ANCHOR}'
    ),
    "neurodegeneration": (
        '("Alzheimer" OR "Parkinson" OR "ALS" OR "amyotrophic lateral sclerosis" OR "Huntington" '
        'OR "dementia" OR "tauopathy" OR "neurodegenerative disease") '
        f'AND {_NEURO_ANCHOR}'
    ),
    "psychiatry": (
        '("depression" OR "schizophrenia" OR "anxiety disorder" OR "bipolar disorder" '
        'OR "PTSD" OR "post-traumatic stress" OR "psychiatric disorder") '
        f'AND {_NEURO_ANCHOR}'
    ),
    "addiction_reward": (
        '("addiction" OR "substance use disorder" OR "reward circuit" OR "dopamine" '
        'OR "reinforcement learning" OR "compulsive behavior") '
        f'AND {_NEURO_ANCHOR}'
    ),
    "developmental_aging": (
        '("neurodevelopment" OR "neurogenesis" OR "synaptic pruning" OR "brain plasticity" '
        'OR "brain aging" OR "cognitive decline" OR "developmental disorder") '
        f'AND {_NEURO_ANCHOR}'
    ),
    "sensory_systems": (
        '("visual system" OR "auditory system" OR "olfaction" OR "somatosensory" OR "pain processing" '
        'OR "vestibular system" OR "sensory perception") '
        f'AND {_NEURO_ANCHOR}'
    ),
    "sleep_circadian": (
        '("sleep" OR "circadian rhythm" OR "arousal" OR "wakefulness" OR "sleep deprivation" '
        'OR "sleep architecture") '
        f'AND {_NEURO_ANCHOR}'
    ),
    "neuropharmacology": (
        '("receptor pharmacology" OR "psychopharmacology" OR "drug mechanism" OR "agonist" '
        'OR "antagonist" OR "neuroactive drug") '
        f'AND {_NEURO_ANCHOR}'
    ),
    "glia_neuroimmunology": (
        '("astrocyte" OR "microglia" OR "neuroinflammation" OR "blood-brain barrier" '
        'OR "glial cell" OR "neuroimmune") '
        f'AND {_NEURO_ANCHOR}'
    ),
    "neuromodulation": (
        '("tDCS" OR "transcranial direct current stimulation" OR "TMS" '
        'OR "transcranial magnetic stimulation" OR "DBS" OR "deep brain stimulation" '
        'OR "closed-loop stimulation") '
        f'AND {_NEURO_ANCHOR}'
    ),
    "bci_neuroeng": (
        '("brain-computer interface" OR "brain computer interface" OR "BCI" '
        'OR "neuroprosthetics" OR "neural decoding" OR "neural engineering") '
        f'AND {_NEURO_ANCHOR}'
    ),
    "electrophysiology": (
        '("EEG" OR "electroencephalography" OR "MEG" OR "single-unit recording" '
        'OR "local field potential" OR "LFP" OR "neural oscillations") '
        f'AND {_NEURO_ANCHOR}'
    ),
    "wearable_neurotech": (
        '("ear-EEG" OR "in-ear EEG" OR "dry electrode" OR "wearable EEG" OR "wearable sensor" '
        'OR "signal quality" OR "mobile brain imaging") '
        f'AND {_NEURO_ANCHOR}'
    ),
}
