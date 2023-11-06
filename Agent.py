# Problem solving agent, do action and change state according to Strategy 

from abc import ABC, abstractmethod
from enum import Enum, auto
from dataclasses import dataclass, field
from typing import Any, Type

from GPTClient import GPTClient
from Evaluator import eval_sampled_functions, Evaluator
from ProblemSampler.ProblemSampler import ProblemSampler, ProblemData

#####################################################################################

# Internal State of the agent, specified by Strategy.
class State:
    pass

# External Observation from GPT or Evaluator, specified by Agent.
class Observation:
    pass

# Request new solution or debug, specified by Agent.
class Action:
    pass

# Give action by State and Observation
class Strategy(ABC):

    @property
    @abstractmethod
    def initial_actions(self) -> list[Action]:
        pass
    
    @abstractmethod
    async def decide(self, obs: Observation) -> Action:
        pass
    
# Do Action
class Agent(ABC):

    @abstractmethod
    def execute(self, action: Action):
        pass

#####################################################################################

class ProgramAgentActionType(Enum):
    # Generation Stage
    GEN_PRETEST         = auto()
    GEN_SOLUTION        = auto() 
    GEN_ANPL            = auto()
    GEN_FUNCTION        = auto()

    # Debug Stage
    GEN_COUNTEREXAMPLE  = auto()
    DEBUG_FUNCTION      = auto() 
    DEBUG_SOLUTION      = auto()

    # Evaluate Stage
    EVAL_PRETEST        = auto()
    EVAL_SYSYEM_TEST    = auto()
    FINISH              = auto()

class ProgramAgentAction(Action):

    def __init__(self, action_type: str, config: dict[str, Any] = {}):
        self.action_type = getattr(ProgramAgentActionType, action_type)
        self.config = config

    def __repr__(self):
        return f'ProgramAgentAction({self.action}, {self.config})'

@dataclass
class ProgramAgentObservation(Observation):
    all_pretests_passed : bool = False
    error_raised        : bool = False

class SelfDebugStrategy(Strategy):

    @dataclass
    class ProgramState(State):
        restart_times        : int = 0
        solution_debug_times : int = 0
        program_debug_times  : int = 0

    def __init__(self,
                 max_restart_times: int = 4,
                 max_solution_debug_times: int = 0,
                 max_program_debug_times: int = 2,
                 num_generated_funcs: int = 16,
                 num_debugged_funcs: int = 8,
                 num_pretests: int = 100,
                 eval_max_attempts: int = 100000,
                 eval_max_time: float = 240,
                 use_pretests_debug: bool = False):

        self.max_restart_times        = max_restart_times
        self.max_solution_debug_times = max_solution_debug_times
        self.max_program_debug_times  = max_program_debug_times
        self.num_generated_funcs      = num_generated_funcs 
        self.num_debugged_funcs       = num_debugged_funcs
        self.num_pretests             = num_pretests
        self.eval_max_attempts        = eval_max_attempts
        self.eval_max_time            = eval_max_time
        self.use_pretests_debug       = use_pretests_debug

        self.ProgramState             = SelfDebugStrategy.ProgramState
        self.state                    = self.ProgramState()

        self.generation_actions       = [
            ProgramAgentAction('GEN_SOLUTION'),
            ProgramAgentAction('GEN_ANPL'),
            ProgramAgentAction('GEN_FUNCTION', {'num_completions': num_generated_funcs}),
            ProgramAgentAction('EVAL_PRETEST', {'max_attempts': eval_max_attempts, 'max_time': eval_max_time})
        ]
        self.finish_actions           = [
            ProgramAgentAction('EVAL_SYSYEM_TEST', {'max_attempts': eval_max_attempts, 'max_time': eval_max_time}),
            ProgramAgentAction('FINISH')
        ]

    def restart(self):
        self.state = self.ProgramState(self.state.restart_times + 1, 0, 0)
        return self.generation_actions
    
    def initial_actions(self):
        return [
            ProgramAgentAction('GEN_PRETEST', {'num_completions': self.num_pretests}),
            *self.generation_actions
        ]
    
    # Maybe request for another LLM, so it should be async
    async def decide(self, obs: ProgramAgentObservation) -> list[ProgramAgentAction]:
        state = self.state

        if obs.all_pretests_passed:
            return self.finish_actions

        if obs.error_raised:
            return self.restart()

        if state.program_debug_times < self.max_program_debug_times:
            state.program_debug_times += 1
            return [
                ProgramAgentAction('GEN_COUNTEREXAMPLE', {
                    'num_completions': self.num_counterexamples,
                    'use_pretests_debug': self.use_pretests_debug
                }),
                ProgramAgentAction('DEBUG_FUNCTION', {'num_completions': self.num_debugged_funcs}),
                ProgramAgentAction('EVAL_PRETEST', {'max_attempts': self.eval_max_attempts, 'max_time': self.eval_max_time})
            ]

        if state.solution_debug_times < self.max_solution_debug_times:
            state.program_debug_times = 0
            state.solution_debug_times += 1
            return [
                ProgramAgentAction('GEN_COUNTEREXAMPLE', {'num_completions': self.num_counterexamples}),
                ProgramAgentAction('DEBUG_SOLUTION'),
                *self.generation_actions[1:]
            ]

        if state.restart_times < self.max_restart_times:
            return self.restart()

        return self.finish_actions 

@dataclass
class Task:
    task_name: str
    save_dir: str
    problem_data: ProblemData 
    evaluator: Evaluator 
    strategy: Strategy
    pretests: list[str]   | None = None
    solutions: list[str]  | None = None
    anpl_codes: list[str] | None = None
    programs: list[str]   | None = None
    error: Exception = None
    running: bool = True 

class ProgramAgent(Agent):

    def __init__(self,
                 client: GPTClient,
                 model_name: str,
                 evaluator_type: Type[Evaluator],
                 strategy_type: Type[Strategy],
                 seed = 42):
        self.client = client
        self.model_name = model_name
        self.evaluator_type = evaluator_type
        self.strategy_type = strategy_type 
        self.seed = seed

    async def dispatch(self, task_name: str, problem_data: ProblemData, save_dir: str, evaluator_config: dict = {}, strategy_config: dict = {}):
        task = Task(task_name, save_dir, problem_data, self.evaluator_type(**evaluator_config), self.strategy_type(**strategy_config))
        await self.main_loop(task)

    async def main_loop(self, task: Task):
        await self.execute(task, task.strategy.initial_actions)
        while task.running:
            obs = await self.observe(task)
            actions = await task.strategy.decide(obs)
            await self.execute(task, actions)

    async def observe(self, task: Task):
        obs = ProgramAgentObservation(
            all_pretests_passed = (len(task.pretests) == len(task.evaluator.best_result[1])),
            error_raised        = (task.error is not None)
        )
        task.error = None
        return obs

    async def execute(self, task: Task, actions: list[ProgramAgentAction]):
        for action in actions:
            action_type = action.action_type.name
            if (func := getattr(self, f'execute_{action_type}')) is not None:
                await func(task, **action.config)
            else:
                raise ValueError(f"Undefined action type {action_type}!")

    async def execute_GEN_PRETEST(self, task, **config):
        pass
    
    async def execute_GEN_SOLUTION(self, task, **config):
        pass
    
    async def execute_GEN_ANPL(self, task, **config):
        pass

    async def execute_GEN_FUNCTION(self, task, **config):
        pass
    
    async def execute_GEN_COUNTEREXAMPLE(self, task, **config):
        pass
    
    async def execute_DEBUG_FUNCTION(self, task, **config):
        pass

    async def execute_DEBUG_SOLUTION(self, task, **config):
        pass
    
    async def execute_EVAL_PRETEST(self, task, **config):
        pass
    
    async def execute_EVAL_SYSYEM_TEST(self, task, **config):
        pass

    async def execute_FINISH(self, task, **config):
        pass


    
