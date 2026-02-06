import ast
import json
import math
import re
import statistics
from datetime import datetime

import numpy as np
import pandas as pd
from flask import current_app

from app.extensions import db
from app.models.import_pipeline import ImportPipeline
from app.services.base import BaseService


class ImportPipelineService(BaseService):
    """Service to manage and execute custom import pipeline scripts."""
    
    model = ImportPipeline

    def create_pipeline(self, name, script_content, description=None, created_by_id=None):
        """Create a new import pipeline after validation."""
        self.validate_script(script_content)
        return self.create(
            name=name,
            script_content=script_content,
            description=description,
            created_by_id=created_by_id
        )

    def update_pipeline(self, pipeline_id, **kwargs):
        """Update an existing import pipeline."""
        pipeline = self.get(pipeline_id)
        if not pipeline:
            raise ValueError(f"Pipeline with ID {pipeline_id} not found.")
        
        if 'script_content' in kwargs:
            self.validate_script(kwargs['script_content'])
            
        return self.update(pipeline, **kwargs)

    def delete_pipeline(self, pipeline_id):
        """Delete an import pipeline."""
        pipeline = self.get(pipeline_id)
        if not pipeline:
            raise ValueError(f"Pipeline with ID {pipeline_id} not found.")
        return self.delete(pipeline)

    def validate_script(self, script_content):
        """
        Validates the script content for safety and required structure.
        - Must define a 'parse(file_path)' function.
        - Must not contain forbidden keywords/modules.
        """
        try:
            tree = ast.parse(script_content)
        except SyntaxError as e:
            raise ValueError(f"Syntax error in script: {str(e)}")

        # Check for 'parse' function definition
        has_parse = False
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == 'parse':
                # Check arguments
                args = node.args.args
                if len(args) != 1:
                    raise ValueError("The 'parse' function must accept exactly one argument: 'file_path'.")
                has_parse = True
                break
        
        if not has_parse:
            raise ValueError("The script must define a function named 'parse(file_path)'.")

        # Forbidden keywords and modules (simple AST check)
        forbidden_modules = {'os', 'sys', 'subprocess', 'shutil', 'socket', 'requests', 'urllib'}
        forbidden_calls = {'eval', 'exec', 'open', 'getattr', 'setattr', 'delattr', 'hasattr'}

        for node in ast.walk(tree):
            # Check imports
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split('.')[0] in forbidden_modules:
                        raise ValueError(f"Import of module '{alias.name}' is forbidden for security reasons.")
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.module.split('.')[0] in forbidden_modules:
                    raise ValueError(f"Import from module '{node.module}' is forbidden for security reasons.")
            
            # Check calls
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    if node.func.id in forbidden_calls:
                        raise ValueError(f"Call to function '{node.func.id}' is forbidden for security reasons.")
                elif isinstance(node.func, ast.Attribute):
                    # Check for things like __subclasses__, __globals__, etc.
                    if node.func.attr.startswith('__'):
                        raise ValueError("Access to double-underscore attributes is forbidden.")

        return True

    def execute_pipeline(self, pipeline_id, file_path):
        """
        Executes a pipeline script from DB safely.
        """
        pipeline = self.get(pipeline_id)
        if not pipeline:
            raise ValueError(f"Pipeline with ID {pipeline_id} not found.")

        return self.execute_script(pipeline.script_content, file_path)

    def execute_script(self, script_content, file_path):
        """
        Executes raw script content safely using asteval.
        """
        try:
            import asteval
            
            # Create a safe interpreter with allowed symbols
            interpreter = asteval.Interpreter()
            
            # Add allowed libraries to the symbol table
            interpreter.symtable['pd'] = pd
            interpreter.symtable['np'] = np
            interpreter.symtable['re'] = re
            interpreter.symtable['math'] = math
            interpreter.symtable['statistics'] = statistics
            interpreter.symtable['datetime'] = datetime
            interpreter.symtable['json'] = json
            
            # Execute the script to define the parse function
            interpreter.eval(script_content)
            
            # Check if parse function was defined
            if 'parse' not in interpreter.symtable:
                raise ValueError("Script successfully executed but 'parse' function was not found.")
            
            # Get the parse function from the symbol table
            parse_func = interpreter.symtable['parse']
            
            # Call the parse function with the file path
            result = parse_func(file_path)
            
            # Convert DataFrame to list of dicts if necessary
            if isinstance(result, pd.DataFrame):
                result = result.to_dict(orient='records')
                
            return result
            
        except Exception as e:
            current_app.logger.error(f"Error executing script: {str(e)}")
            raise RuntimeError(f"Script execution failed: {str(e)}")
