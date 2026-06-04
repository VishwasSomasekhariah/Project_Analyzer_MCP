"""
.. deprecated::
    Not used by any active MCP tools. Part of the deprecated IR pipeline.

IR Validators - 3-layer validation for QueryIR.

Validation Layers:
1. Syntax (Layer 1): Well-formedness of IR structure
2. Schema (Layer 2): Validate against graph schema
3. Semantic (Layer 3): Domain-specific intent rules

Usage:
    from src.core.graph_rag.ir.validators import IRValidator

    validator = IRValidator(schema_info)
    result = validator.validate(ir)

    if not result.valid:
        print(result.to_feedback())
"""

from .ir_validator import IRValidator
from .intent_rules import IntentRuleEngine

__all__ = [
    'IRValidator',
    'IntentRuleEngine',
]
