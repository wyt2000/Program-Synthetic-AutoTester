import functools
import traceback
import sys
import importlib.util
import functools
import timeout_decorator
from copy import deepcopy
from types import FunctionType, ModuleType
import io
from contextlib import redirect_stdout
import resource
import code
import ast

# Import program str as module.
def import_module_from_string(source: str):
    spec = importlib.util.spec_from_loader("test", loader=None)
    module = importlib.util.module_from_spec(spec)
    exec(source, module.__dict__)
    return module

class TraceException(Exception):
    '''
    Exception with lineno in str module.
    '''
    def __init__(self,
                 lineno: int,
                 func_name: str,
                 *args):
        super().__init__(*args)
        self.lineno = lineno
        self.func_name = func_name

    def __repr__(self):
        return f"{super().__repr__()} at line {self.lineno} in function \'{self.func_name}\'"

class IOExample:
    '''
    input-output pair with exception for function.
    '''
    def __init__(self,
                 inp: dict[str, str],
                 out: str,
                 exc: Exception = None):
        self.input     = inp
        self.output    = out
        self.exception = exc 

    def __repr__(self):
        if self.exception is None:
            return f'input: {repr(self.input)}, output: {repr(self.output)}'
        return f'input: {repr(self.input)}, {repr(self.exception)}'

class IOCollector:
    '''
    Wrap func in module to record input/output when exec.
    '''
    def __init__(self,
                 func_names: list[str],
                 module: ModuleType,
                 limit: int= 3):

        self.func_names = func_names
        self.func_ios   = {}
        self.limit      = limit

        # Trace all functions in func_names
        for name in func_names:
            func = getattr(module, name, None)
            if func and isinstance(func, FunctionType):
                setattr(module, name, self.set_trace(func))
    
    def __repr__(self):
        return f"IOCollector({self.func_ios})"

    # Wrap function to save I/O in func_ios when execuated
    def set_trace(self, func: FunctionType):

        @functools.wraps(func)
        def wrapper(*args, **kwargs):

            # Get formal args and actual args
            names, values = func.__code__.co_varnames[:func.__code__.co_argcount], args
            inputs = {name: value for name, value in zip(names, values)}
            if kwargs:
                inputs = inputs | kwargs

            # Exec functions and copy ios or exception
            frozen_inputs = deepcopy(inputs)
            output = None
            exc = None
            try:
                output = func(*args, **kwargs)
            except TraceException as te:
                exc = te
            except Exception as e:
                te = traceback.TracebackException.from_exception(e)
                lineno = te.stack[-1].lineno if te.stack else -1
                func_name = te.stack[-1].name if te.stack else ""
                exc = TraceException(lineno, func_name, f"{e.__class__.__name__}: {e}")
            frozen_output = deepcopy(output)

            # Save trace as IOExample
            func_name = func.__name__
            if func_name not in self.func_ios:
                self.func_ios[func_name] = []
            if len(self.func_ios[func_name]) < self.limit:
                self.func_ios[func_name].append(IOExample(frozen_inputs, frozen_output, exc))

            # Handle exception
            if exc:
                raise exc
            return output
        return wrapper

# Run code while catching time and memory limit exception
@timeout_decorator.timeout(1)
def exec_with_limit(func: FunctionType,
                    inputs: str):
    with redirect_stdout(io.StringIO()):
        soft, hard = resource.getrlimit(resource.RLIMIT_AS)
        resource.setrlimit(resource.RLIMIT_AS, (1 << 32, hard))
        try:
            func(inputs)
        finally:
            resource.setrlimit(resource.RLIMIT_AS, (soft, hard))

# TODO: support non-main function as entry
def exec_with_trace(code: str,
                    func_names: list[str],
                    inputs: str,
                    entry_name: str = 'main') -> list[IOCollector, Exception]:
    '''
    Run code and save traces of func_names
    '''
    # Load module from code and find entry function
    module = import_module_from_string(code)
    io = IOCollector(func_names, module)
    entry_func = getattr(module, entry_name, None)
    if not (entry_func and isinstance(entry_func, FunctionType)):
        raise ValueError(f"Couldn't find entry function {entry}")
    exc = None
    try:
        exec_with_limit(entry_func, inputs)
    except Exception as err:
        exc = err 
    return io, exc 

# Trace all functions in code
def trace_code(code: str, inputs: str) -> list[IOCollector, Exception]:
    # Parse code to ast.Node
    try:
        root = ast.parse(code)
    except Exception as err:
        raise Exception("Syntax Error in code!")
    assert isinstance(root, ast.Module)

    # Get function names
    func_names = []
    for node in root.body:
        if isinstance(node, ast.FunctionDef):
            func: ast.FunctionDef = node
            func_names.append(func.name)

    return exec_with_trace(code, func_names, inputs)

if __name__ == '__main__':
    # TEST 1: function I/O trace
    code = '''
def add(x: int, i: int):
    return x + i
def add_list(inputs: list[int]):
    for i in range(len(inputs)):
        inputs[i] = add(inputs[i], i)
    return inputs
def parse_input(input_str: str):
    input_list = list(map(int, input_str.split()))
    return input_list
def main(input_str: str):
    inputs = parse_input(input_str)
    return add_list(inputs)
    '''
    ios, exc = trace_code(code, "1 2 3 4 5")
    print(ios, exc)
    
    # TEST 2: Runtime Error
    code = '''
def re(inputs: str):
    return inputs[100]
def parse_input(input_str: str):
    return input_str
def main(input_str: str):
    inputs = parse_input(input_str)
    return re(inputs)
    '''
    ios, exc = trace_code(code, "123")
    print(ios, exc)


