import sys
from pathlib import Path

# Add project root to path (for shared package)
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
# Add app directory to path (for llm_helper)
sys.path.insert(0, str(Path(__file__).parent.parent))
