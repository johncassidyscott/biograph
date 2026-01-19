"""
BioGraph MVP v8.2

Index-anchored intelligence graph for life sciences.
Per docs/spec/BioGraph_Master_Spec_v8.2_MVP.txt

CORE CONTRACTS:
- Evidence-first: No assertions without >=1 evidence
- License gates: Evidence must have allowlisted license
- Fixed chains: Issuer → DrugProgram → Target → Disease ONLY
- Query surface: Explanation table is ONLY product interface
- ML suggests, humans decide: No auto-canonical creation
"""

__version__ = "8.2.0"
