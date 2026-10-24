# AKOR workspace

Run these in this directory:

```text
oz send P --id first
oz send r1 --to reviewer --id check --after first
oz plan
oz status
```

For a real agent, choose the JSON stdin/stdout adapter explicitly:

`oz run --adapter adapter.json`

adapter.json: {"argv":["python","worker.py"],"protocols":["oz.adapter/3"],"languages":["OZ/9"]}
The adapter passes the prompt to the model and returns {"reply":...,"usage":...} (see OZ9.md).
The command runs in the adapter file's directory. oz init never runs an adapter.
oz.json holds the channels, the target tokenizer, the input budget and the batch size.
For a new source or codebook, add a channel: oz channel-add new-channel channel.json
To see the result of a finished job: oz inspect first
