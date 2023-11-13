import yaml
import os
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, TrainingArguments
from datasets import load_dataset
from peft import LoraConfig
from trl import SFTTrainer


def load_model(bootstrap_config, train_run_config):
    if bootstrap_config["model_type"] == "hf":
        model = AutoModelForCausalLM.from_pretrained(bootstrap_config["model_name"], quantization_config=train_run_config["bnb_config"], trust_remote_code=True)
        tokenizer = AutoTokenizer.from_pretrained(bootstrap_config["model_name"], trust_remote_code=True)
    else:
        model = AutoModelForCausalLM.from_pretrained(bootstrap_config["model_mount_path"], quantization_config=train_run_config["bnb_config"])
        tokenizer = AutoTokenizer.from_pretrained(bootstrap_config["model_mount_path"])
    return model, tokenizer

def fetch_dataset(bootstrap_config):
    if bootstrap_config["dataset_type"] == "hf":
        dataset = load_dataset(bootstrap_config["dataset_name"], split="train")
    else:
        dataset = load_dataset("csv", data_files=os.path.join(bootstrap_config["dataset_mount_path"], bootstrap_config["dataset_name"]), split="train")
    return dataset, bootstrap_config["dataset_training_column"]

def load_train_config(bootstrap_config):
    if bootstrap_config["bnb_config_path"] and os.path.isfile(os.path.join(bootstrap_config["bnb_config_path"], bootstrap_config["config_suffix"])):
        bnb_config_args = yaml.safe_load(os.path.join(bootstrap_config["bnb_config_path"], bootstrap_config["config_suffix"]))
        bnb_config = BitsAndBytesConfig(**bnb_config_args)
    else:
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.float16,
        )

    if bootstrap_config["peft_config_path"] and os.path.isfile(os.path.join(bootstrap_config["peft_config_path"], bootstrap_config["config_suffix"])):
        peft_config_args = yaml.safe_load(os.path.join(bootstrap_config["peft_config_path"], bootstrap_config["config_suffix"]))
        peft_config = LoraConfig(**peft_config_args)
    else:
        peft_config = LoraConfig(
            lora_alpha=16,
            lora_dropout=0.1,
            r=64,
            bias="none",
            task_type="CAUSAL_LM",
            target_modules=[
                "query_key_value",
                "dense",
                "dense_h_to_4h",
                "dense_4h_to_h",
            ]
        )        

    checkpoint_path = bootstrap_config["checkpoint_path"]
    if bootstrap_config["training_config_path"] and os.path.isfile(os.path.join(bootstrap_config["training_config_path"], bootstrap_config["config_suffix"])):
        training_config_args = yaml.safe_load(os.path.join(bootstrap_config["training_config_path"], bootstrap_config["config_suffix"]))
        training_config = TrainingArguments(output_dir = checkpoint_path, **training_config_args)
    else:
        training_config = TrainingArguments(
            output_dir=checkpoint_path,
            per_device_train_batch_size=4,
            gradient_accumulation_steps=4,
            optim="paged_adamw_32bit",
            save_steps=10,
            logging_steps=10,
            learning_rate=2e-4,
            fp16=True,
            max_grad_norm=0.3,
            max_steps=500,
            warmup_ratio=0.03,
            group_by_length=True,
            lr_scheduler_type="constant",
            gradient_checkpointing=True,
        )
    return {"peft_config": peft_config, "training_config": training_config, "bnb_config": bnb_config}  

def do_train(dataset, train_column_name, model, tokenizer, train_run_config):

    # Note that default configurations are intended for falcoln 7B model
    dataset = dataset.shuffle()

    #os.environ["WANDB_DISABLED"] = "true"
    # Assumes model is a causal language model
    model.config.use_cache = False

    # May need to have some custom padding logic here
    tokenizer.pad_token = tokenizer.eos_token

    # TODO : need to parametrize this
    max_seq_length = 512

    trainer = SFTTrainer(
        model=model,
        train_dataset=dataset,
        peft_config=train_run_config["peft_config"],
        dataset_text_field=train_run_config["dataset_training_column"],
        max_seq_length=max_seq_length,
        tokenizer=train_run_config["tokenizer"],
        args=train_run_config["training_config"]
    )

    ## TODO : Remove, falcoln 7B specific training code
    for name, module in trainer.model.named_modules():
        if "norm" in name:
            module = module.to(torch.float32)

    trainer.train()






