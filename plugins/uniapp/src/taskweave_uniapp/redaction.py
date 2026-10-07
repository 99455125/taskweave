"""One known-value policy for runner lookahead, metadata and parsed reports."""
import json
import re
from taskweave_process.runner import redact_text


def representations(secrets):
    values=set(filter(None,secrets));previous=list(values)
    # Standard JSON serializers and common nested diagnostic serialization.
    # Arbitrary encodings and deeper wrappers are deliberately not inferred.
    for _ in range(2):
        encoded=[json.dumps(value,ensure_ascii=ascii_mode)[1:-1] for value in previous for ascii_mode in (True,False)]
        previous=[]
        for value in encoded:
            variants=(value,re.sub(r'\\u([0-9a-fA-F]{4})',lambda match:'\\u'+match[1].upper(),value))
            previous.extend(variants);values.update(variants)
    return tuple(sorted(values,key=len,reverse=True))


def mask_data(value,patterns):
    if isinstance(value,str):return redact_text(value,patterns)
    if isinstance(value,list):return [mask_data(item,patterns) for item in value]
    if isinstance(value,dict):return {redact_text(key,patterns):mask_data(item,patterns) for key,item in value.items()}
    return value
