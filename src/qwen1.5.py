import os
import json
import torch
import numpy as np
import argparse
from mp_utils import choices, format_example, gen_prompt, softmax, run_eval
from tqdm import tqdm
import requests

from transformers import AutoModelForCausalLM, AutoTokenizer
from transformers.generation import GenerationConfig

# qwen1.5-14b-chat
url = "http://172.27.221.13:9002/v1/chat/completions"
model_name = "Qwen1.5-14B-Chat"

MODEL_DIR = f"/data/models/{model_name}"
SAVE_DIR = f"../results/{model_name}"


def is_eval_success(args) -> bool:
    """judege if eval task is success by checking the result dir"""
    subjects = sorted(
        [f.split(".csv")[0]
         for f in os.listdir(os.path.join(args.data_dir, "test/"))]
    )
    abs_save_dir = f"{args.save_dir}_{args.num_few_shot}_shot"
    if not os.path.exists(abs_save_dir):
        return False
    for subject in subjects:
        out_file = os.path.join(abs_save_dir, f"results_{subject}.csv")
        if not os.path.exists(out_file):
            # If any result file NOT exist, the eval isn't finished
            return False
    return True


def init_model(args):
    """Initialize models"""
    # model = AutoModelForCausalLM.from_pretrained(
    #     args.model_name_or_path,
    #     trust_remote_code=True,
    #     device_map="auto",
    #     torch_dtype=torch.float16,
    # )
    # model.generation_config = GenerationConfig.from_pretrained(
    #     args.model_name_or_path, trust_remote_code=True
    # )
    # return model
    return None


def remote_predict(prompt, max_tokens=512):
    """
    调用服务端接口进行推理
    """
    headers = {'Content-Type': 'application/json'}
    data = {
        "model": model_name,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens
    }
    response = requests.post(url, headers=headers, data=json.dumps(data))
    # print("response: ", response.json(), "\n\n")
    print("response: ", response)
    return response.json()['choices'][0]['message']['content']
    # return response.json().get("response")


def eval(model, tokenizer, subject, dev_df, test_df, num_few_shot, max_length, cot):
    choice_ids = [tokenizer(choice)["input_ids"][0] for choice in choices]
    cors = []
    all_conf = []
    all_preds = []
    answers = choices[: test_df.shape[1] - 2]

    for i in range(test_df.shape[0]):
        prompt_end = format_example(
            test_df, i, subject, include_answer=False, cot=cot)
        prompt = gen_prompt(
            dev_df=dev_df,
            subject=subject,
            prompt_end=prompt_end,
            num_few_shot=num_few_shot,
            tokenizer=tokenizer,
            max_length=max_length,
            cot=cot,
        )
        label = test_df.iloc[i, test_df.shape[1] - 1]

        # with torch.no_grad():
        #     input_ids = tokenizer([prompt], padding=False)["input_ids"]
        #     input_ids = torch.tensor(input_ids, device=model.device)
        #     logits = model(input_ids)["logits"]
        #     last_token_logits = logits[:, -1, :]
        #     if last_token_logits.dtype in {torch.bfloat16, torch.float16}:
        #         last_token_logits = last_token_logits.to(dtype=torch.float32)
        #     choice_logits = last_token_logits[:, choice_ids].detach().cpu().numpy()
        #     conf = softmax(choice_logits[0])[choices.index(label)]
        #     pred = {0: "A", 1: "B", 2: "C", 3: "D"}[np.argmax(choice_logits[0])]

        # all_preds += pred
        # all_conf.append(conf)
        # cors.append(pred == label)

        # 通过 HTTP 调用远程服务
        pred = remote_predict(prompt, max_tokens=max_length)
        print("pred:", pred)

        if pred and pred[0] in choices:
            cors.append(pred[0] == label)
        all_preds.append(pred.replace("\n", ""))

    acc = np.mean(cors)
    print("Average accuracy {:.3f} - {}".format(acc, subject))
    return acc, all_preds, None


def eval_chat(
    model, tokenizer, subject, dev_df, test_df, num_few_shot, max_length, cot
):
    """eval Qwen/Qwen1.5-7B-Chat
    ref: https://github.com/QwenLM/Qwen1.5?tab=readme-ov-file#quickstart
    """
    cors = []
    all_preds = []
    answers = choices[: test_df.shape[1] - 2]

    for i in tqdm(range(test_df.shape[0])):
        prompt_end = format_example(
            test_df, i, subject, include_answer=False, cot=cot)
        prompt = gen_prompt(
            dev_df=dev_df,
            subject=subject,
            prompt_end=prompt_end,
            num_few_shot=num_few_shot,
            tokenizer=tokenizer,
            max_length=max_length,
            cot=cot,
        )
        label = test_df.iloc[i, test_df.shape[1] - 1]

        text = tokenizer.apply_chat_template(
            [{"role": "user", "content": prompt}],
            tokenize=False,
            add_generation_prompt=True,
        )
        model_inputs = tokenizer([text], return_tensors="pt").to(model.device)

        generated_ids = model.generate(
            model_inputs.input_ids, max_new_tokens=512)
        generated_ids = [
            output_ids[len(input_ids):]
            for input_ids, output_ids in zip(model_inputs.input_ids, generated_ids)
        ]

        pred = tokenizer.batch_decode(
            generated_ids, skip_special_tokens=True)[0]
        # pred, history = model.chat(tokenizer, prompt, history=None)

        if pred and pred[0] in choices:
            cors.append(pred[0] == label)
        all_preds.append(pred.replace("\n", ""))

    acc = np.mean(cors)
    print("Average accuracy {:.3f} - {}".format(acc, subject))
    print(
        "{} results, {} inappropriate formated answers.".format(
            len(cors), len(all_preds) - len(cors)
        )
    )
    return acc, all_preds, None


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model_name_or_path", type=str, default=MODEL_DIR)
    parser.add_argument("--data_dir", type=str, default="../data")
    parser.add_argument("--save_dir", type=str, default=SAVE_DIR)
    parser.add_argument("--num_few_shot", type=int, default=0)
    parser.add_argument("--max_length", type=int, default=2048)
    parser.add_argument("--cot", action="store_true")
    args = parser.parse_args()

    tokenizer = AutoTokenizer.from_pretrained(
        args.model_name_or_path, trust_remote_code=True
    )
    if is_eval_success(args):
        # eval finished, no need load model anymore, just show the result
        model = None
    else:
        model = init_model(args)

    run_eval(model, tokenizer, eval, args)

    # if "chat" in args.model_name_or_path.lower():
    #     run_eval(model, tokenizer, eval_chat, args)
    # else:
    #     run_eval(model, tokenizer, eval, args)
