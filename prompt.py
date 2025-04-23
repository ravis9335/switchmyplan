from openai import OpenAI

client = OpenAI(
  api_key= "sk-svcacct-t_Y2DrvNAYHIXqMxlhLZ-A4rr3UaeicVsrDlL1rwM2H6sPqbEwRjTSwAGcaGPT3BlbkFJ5nDSoc2TljviekVgYy9IabYBFBt5XXgT5IelJbQGSITR35NqInXSQwoYRzGAA"
)

completion = client.chat.completions.create(
  model="gpt-4o-mini",
  store=True,
  messages=[
    {"role": "user", "content": "write a haiku about ai"}
  ]
)

print(completion.choices[0].message);
