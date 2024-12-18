set -x
cd ../src

#python qwen2.py \
#    --model_name_or_path Qwen/Qwen1.5-72B \
#    --save_dir ../results/Qwen1.5-72B \
#    --num_few_shot 5
CUDA_VISIBLE_DEVICES=1 python qwen2.py \
    --model_name_or_path /data/models/Qwen2-72B-Instruct-GPTQ-Int4 \
    --save_dir ../results/qwen2-72b-huawei \
    --num_few_shot 0
