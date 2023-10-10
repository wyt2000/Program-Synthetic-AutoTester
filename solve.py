from GPTClient import GPTClient
from ProblemSampler.APPSProblemSampler import APPSProblemSampler, APPSProblemData
from Prompter.Prompter import AbstractPrompter
from Prompter.ANPLPrompter import ANPLPrompter 
from Synthesizer.Synthesizer import AbstractSynthesizer 
from Synthesizer.ANPLSynthesizer import ANPLSynthesizer 
from utils import mkdir_override

import logging
import logging.config
import argparse
import asyncio
import json
import pathlib
import time

logging.config.fileConfig('logging.conf')
logger = logging.getLogger('main')

async def solve_problem(task_name: str,
                        model_name: str,
                        client: GPTClient,
                        prompter: AbstractPrompter,
                        synthesizer: AbstractSynthesizer,
                        data: APPSProblemData,
                        num_completions: int,
                        save_dir: str,
                        delay_in_seconds: int = 1,
                        max_restart_times: int = 1):

    logger.debug(f"{task_name}: start to solve the problem...")
    mkdir_override(save_dir)
    restart_times = 0
    debug_solution_times = 0
    solution = None
    system_test = json.loads(data.input_output)

    # Try to solve the problem until reach max_restart_times
    while restart_times < max_restart_times:

        # Generate new solution or use debugged solution
        if solution is None:
            logger.debug(f"{task_name}_{restart_times}_0: Generating new solution...")
            solution = await client.request_for_solutions(
                task_name         = f"{task_name}_{restart_times}",
                completion_kwargs = {
                    "model"       : model_name,
                    "temperature" : 0.6,
                    "logit_bias"  : {755:-100}
                },
                question          = data.question,
                prompter          = prompter,
                save_dir          = save_dir,
                delay_in_seconds  = delay_in_seconds
            )
            solution = solution[0]

        logger.debug(f"{task_name}_{restart_times}_{debug_solution_times}: Generating anpl code...")
        # Generate anpl code from solution
        anpl_code = await client.request_for_codes(
            task_name         = f"{task_name}_{restart_times}_{debug_solution_times}",
            completion_kwargs = {
                "model"             : model_name,
                "temperature"       : 0.2,
                "presence_penalty"  : 0.1,
            },
            starter_code      = "",
            solution          = solution,
            suffix_name       = "anpl",
            prompter          = prompter,
            save_dir          = save_dir,
            delay_in_seconds  = delay_in_seconds
        )

        # Synthesize python code from anpl code
        logger.debug(f"{task_name}_{restart_times}_{debug_solution_times}: Synthesizer python code...")
        try:
            log_path = Path(save_dir, f"{task_name}_{i}.log")
            file_handler = logging.FileHandler(log_path)
            root_logger = logging.getLogger('root')
            root_handlers = [root_logger.handlers[0]]
            root_logger.handlers = [file_handler]
            synthesizer.synthesize(
                f"{task_name}_{i}",
                code,
                Path(save_dir, f"{task_name}_{i}"),
                Path(cache_dir, f"{task_name}_{i}"),
                question,
                inputs,
                outputs,
                [k]
            )
        except Exception as err:
            logger.exception(err)
        finally:
            file_handler.close()
            root_logger.handlers = root_handlers

        

        restart_times += 1
    

if __name__ == '__main__':

    argparser = argparse.ArgumentParser()
    argparser.add_argument("-p", "--num_problems", help="Number of problems", type=int, default=1)
    argparser.add_argument("-k", "--num_completions", help="Number of function implementations for each code", type=int, default=4)
    args = argparser.parse_args()

    sampler = APPSProblemSampler(difficulties=['competition'])
    client = GPTClient()
    prompter = ANPLPrompter()
    synthesizer = ANPLSynthesizer()

    timestr = time.strftime("%m%d%H%M%S")
    save_prefix = f'anpl_apps_{timestr}'
    mkdir_override(save_prefix)

    logger.debug(f"There are {args.num_problems} problems to be solved!") 
    for data in sampler.sample_randomly(args.num_problems):
        try:
            save_dir = pathlib.Path(save_prefix, f'{data.problem_id}')
            asyncio.run(
                solve_problem(
                    task_name           = f"apps_{data.problem_id}",
                    model_name          = "gpt-3.5-turbo-0301", 
                    client              = client,
                    prompter            = prompter,
                    synthesizer         = synthesizer,
                    data                = data,
                    num_completions     = args.num_completions,
                    save_dir            = str(save_dir)
                )
            )
        except Exception as err:
            logger.exception(err)

