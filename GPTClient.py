import openai
import logging 
import logging.config
import aiohttp
import pathlib
import json
from PromptBuilder.PromptBuilder import AbstractPromptBuilder

class GPTClient:

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    async def request(self, task_name, model_name, question, starter_code, prompt_builder: AbstractPromptBuilder, save_dir=None):
        async with aiohttp.ClientSession(trust_env=True) as session:
            openai.aiosession.set(session)
            # Solution Stage
            messages = prompt_builder.build_background()
            messages = prompt_builder.build_solution_request(question, messages)
            self.logger.debug(f'{task_name}: Requesting for high-level solution from {model_name}...')
            response = await openai.ChatCompletion.acreate(
                    model       = model_name,
                    messages    = messages,
                    temperature = 0.6
            )
            solution_plan = prompt_builder.get_response(response, messages)
            self.logger.debug(f'{task_name}: Requesting for high-level solution done!')
            # Translation Stage
            messages = prompt_builder.build_translation_request(solution_plan, starter_code, messages)
            self.logger.debug(f'{task_name}: Requesting for code from {model_name}...')
            response = await openai.ChatCompletion.acreate(
                    model            = model_name,
                    messages         = messages,
                    temperature      = 0.2,
                    presence_penalty = 0.1
            )
            code = prompt_builder.get_response(response, messages)
            code = prompt_builder.extract_code(code)
            self.logger.debug(f'{task_name}: Requesting for code solution done!')
            if save_dir is not None:
                with open(pathlib.Path(save_dir, f'{task_name}.py'), 'w') as f:
                    f.write(code)
            return code

