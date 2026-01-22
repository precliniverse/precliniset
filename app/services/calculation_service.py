import math
import re
from simpleeval import simple_eval, NameNotDefined

class CalculationService:
    """
    Service to handle calculation of derived analytes based on formulas.
    """
    
    def calculate_row(self, row_data, protocol_analytes):
        """
        Calculates values for analytes with formulas in a single row.
        
        :param row_data: Dict of {analyte_name: value}
        :param protocol_analytes: List of ProtocolAnalyteAssociation objects
        :return: Updated row_data with calculated values
        """
        # 1. Identify calculated fields
        calculated_associations = [a for a in protocol_analytes if a.calculation_formula]
        if not calculated_associations:
            return row_data
            
        # 2. Build Mapping for [#1], [#2] references
        index_to_name = {}
        for i, assoc in enumerate(protocol_analytes, 1):
            index_to_name[str(i)] = assoc.analyte.name

        # 3. Prepare Context and math functions
        functions = {
            'sqrt': math.sqrt,
            'log': math.log,
            'log10': math.log10,
            'exp': math.exp,
            'abs': abs,
            'round': round,
            'min': min,
            'max': max,
            'pow': pow
        }

        updated_row = row_data.copy()
        
        # Max 5 passes to resolve nested dependencies (A depends on B depends on C...)
        for pass_num in range(5): 
            changes_made = False
            for assoc in calculated_associations:
                target_col = assoc.analyte.name
                formula = assoc.calculation_formula
                
                # Check for indexed variables [#1], [#2] and replace them with [Analyte Name]
                indexed_vars = re.findall(r'\[#(\d+)\]', formula)
                working_formula = formula
                for idx in indexed_vars:
                    if idx in index_to_name:
                        actual_name = index_to_name[idx]
                        working_formula = working_formula.replace(f"[#{idx}]", f"[{actual_name}]")
                
                # Find all [Variables] in the updated formula
                vars_in_formula = re.findall(r'\[(.*?)\]', working_formula)
                
                eval_expression = working_formula
                is_computable = True
                safe_context = functions.copy()
                
                for var_name in vars_in_formula:
                    # Look in updated_row instead of row_data to support dependency chains
                    val = updated_row.get(var_name)
                    
                    if val in [None, '']:
                        is_computable = False
                        break
                    
                    try:
                       f_val = float(val)
                    except (ValueError, TypeError):
                       is_computable = False 
                       break
                       
                    # Replace [Variable Name] with a safe token in expression and context
                    token = f"var_{abs(hash(var_name))}"
                    safe_context[token] = f_val
                    eval_expression = eval_expression.replace(f"[{var_name}]", token)
                
                if not is_computable:
                    continue

                try:
                    # Evaluate using simple_eval
                    result = simple_eval(eval_expression, names=safe_context)
                    
                    # Basic numeric cleanup
                    if isinstance(result, (int, float)):
                        if isinstance(result, float) and (math.isnan(result) or math.isinf(result)):
                            result = None
                        elif isinstance(result, float):
                            result = round(result, 4)
                    
                    # Update row if value changed
                    if updated_row.get(target_col) != result:
                        updated_row[target_col] = result
                        changes_made = True
                except (ZeroDivisionError, NameNotDefined, SyntaxError):
                    continue 
                except Exception:
                    continue
            
            if not changes_made:
                break
                
        return updated_row
