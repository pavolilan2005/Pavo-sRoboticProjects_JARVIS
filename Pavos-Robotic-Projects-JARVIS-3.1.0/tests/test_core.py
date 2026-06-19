from pathlib import Path
import numpy as np
from prp.core.config import ConfigStore
from prp.core.capabilities import CapabilityRegistry
from prp.services.audio import AudioService
def test_resample_duration():
 x=(np.zeros(16000,dtype=np.int16)).tobytes(); y=AudioService._resample_bytes(x,16000,48000); assert len(y)==16000*3*2
def test_no_duplicate_serial_import():
 root=Path(__file__).parents[1];hits=[]
 for p in root.rglob('*.py'):
  if 'import serial' in p.read_text(encoding='utf-8'):hits.append(p.name)
 assert hits==['serial_service.py']
