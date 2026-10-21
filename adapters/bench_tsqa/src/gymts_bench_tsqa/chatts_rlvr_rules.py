# Copyright 2024 Tsinghua University and ByteDance.
#
# Licensed under the MIT License (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://opensource.org/license/mit
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Adapted from open-r1-zzr reward_qa.py at dc2dcb091f5268fb4c87b89584f2ac120a095e5e.
# Only deterministic Dataset A RLVR rules are included. See UPSTREAM.md.
import re
from typing import List


def split_sentences(text):
    abbreviations = ['max.', 'eg.', 'Mrs.', 'Dr.', 'Mr.']
    
    for abbr in abbreviations:
        escaped_abbr = re.escape(abbr)
        text = re.sub(escaped_abbr, abbr.replace('.', '<DOT>'), text)

    pattern = r'[.!?。！？,;，；](?!\d)'
    sentences = re.split(pattern, text)
    
    sentences = [s.strip().replace('<DOT>', '.') for s in sentences if s.strip()]
    
    return sentences

def split_period_sentences(text):
    abbreviations = ['max.', 'eg.', 'Mrs.', 'Dr.', 'Mr.']
    
    for abbr in abbreviations:
        escaped_abbr = re.escape(abbr)
        text = re.sub(escaped_abbr, abbr.replace('.', '<DOT>'), text)

    pattern = r'[.。](?!\d)'
    sentences = re.split(pattern, text)
    
    sentences = [s.strip().replace('<DOT>', '.') for s in sentences if s.strip()]
    
    return sentences

def match_metric_name(metric: str, sentence: str) -> bool:
    pattern = r'[^\u4e00-\u9fa5a-zA-Z]'
    sentence = re.sub(pattern, '', sentence).lower()
    metric = re.sub(pattern, '', metric).lower()

    return metric in sentence

def evaluate_trend(answer: str, attribute: dict, cols: List[str]):
    cate_correct = False
    sentences = split_sentences(answer)

    if len(sentences) == 0:
        return [0.0], [0.0], [], []

    if 'steady' in attribute['type']:
        if 'steady' in sentences[0]:
            cate_correct = True
    elif 'decrease' in attribute['type']:
        if 'decreas' in sentences[0].lower():
            cate_correct = True
    elif 'increase' in attribute['type']:
        if 'increas' in sentences[0].lower():
            cate_correct = True

    num_correct = []

    # Check start point
    for sentence in sentences:
        float_numbers = list(map(float, re.findall(r'-?\d+\.?\d*', sentence)))
        if float_numbers is None or len(float_numbers) == 0:
            continue
        if 'start' in sentence:
            if abs(attribute['start']) < 0.5:
                if abs(float_numbers[0]) < 0.5:
                    num_correct.append(1.0)
                else:
                    num_correct.append(0.0)
            else:
                num_correct.append(max(0.0, min(1.0, 1.0 - abs(float_numbers[0] - attribute['start']) / abs(attribute['start']))))
            break
    else:
        num_correct.append(0.0)

    # Check amplitude
    if attribute['type'] != 'keep steady':
        for sentence in sentences:
            float_numbers = list(map(float, re.findall(r'-?\d+\.?\d*', sentence)))
            if float_numbers is None or len(float_numbers) == 0:
                continue
            if 'change value' in sentence or 'from left to right' in sentence:
                if abs(attribute['amplitude']) < 0.5:
                    if abs(float_numbers[0]) < 0.5:
                        num_correct.append(1.0)
                    else:
                        num_correct.append(0.0)
                else:
                    num_correct.append(max(0.0, min(1.0, 1.0 - abs(float_numbers[0] - attribute['amplitude']) / abs(attribute['amplitude']))))
                break
        else:
            num_correct.append(0.0)

    return [cate_correct], num_correct, [], []

def evaluate_season(answer: str, attribute: dict, cols: List[str]):
    cate_correct = False
    sentences = split_sentences(answer)

    if len(sentences) == 0:
        return [0.0], [0.0], [], []

    if 'no' in attribute['type']:
        if 'no periodic' in sentences[0].lower():
            cate_correct = True
    else:
        if 'no' not in sentences[0].lower() and 'periodic' in sentences[0].lower():
            cate_correct = True

    num_correct = []

    if attribute['type'] != 'no periodic fluctuation':
        # Check period
        for sentence in sentences:
            float_numbers = list(map(float, re.findall(r'-?\d+\.?\d*', sentence)))
            if float_numbers is None or len(float_numbers) == 0:
                continue
            if 'each period' in sentence:
                num_correct.append(max(0.0, min(1.0, 1.0 - abs(float_numbers[0] - attribute['period']) / abs(attribute['period']))))
                break
        else:
            num_correct.append(0.0)

        # Check amplitude
        for sentence in sentences:
            float_numbers = list(map(float, re.findall(r'-?\d+\.?\d*', sentence)))
            if float_numbers is None or len(float_numbers) == 0:
                continue
            if 'amplitude' in sentence:
                num_correct.append(max(0.0, min(1.0, 1.0 - abs(float_numbers[0] - attribute['amplitude']) / abs(attribute['amplitude']))))
                break
        else:
            num_correct.append(0.0)
    else:
        num_correct = []

    return [cate_correct], num_correct, [], []

def evaluate_noise(answer: str, attribute: dict, cols: List[str]):
    cate_correct = False
    sentences = split_sentences(answer)

    if len(sentences) == 0:
        return [0.0], [0.0], [], []

    if 'almost no' in attribute['type']:
        if 'no noise' in sentences[0].lower():
            cate_correct = True
    else:
        if 'noisy' in sentences[0].lower():
            cate_correct = True

    num_correct = []

    # Check period
    if 'noisy' in attribute['type']:
        for sentence in sentences:
            float_numbers = list(map(float, re.findall(r'-?\d+\.?\d*', sentence)))
            if float_numbers is None or len(float_numbers) == 0:
                continue
            if 'standard' in sentence.lower() or 'std' in sentence.lower():
                num_correct.append(max(0.0, min(1.0, 1.0 - abs(float_numbers[0] - attribute['std']) / abs(attribute['std']))))
                break
        else:
            num_correct.append(0.0)

    return [cate_correct], num_correct, [], []

def evaluate_local(answer: str, attribute: dict, cols: List[str]):
    cate_correct = []
    num_correct = []

    # Split into facts
    if len(attribute) == 0 and "no " in answer.lower():
        return [True], [], [], []

    for feat in attribute:
        matched_flag = False
        pos_numerical = 0.0
        amp_numerical = 0.0
        for fact in re.split(r'[;；]', answer):
            sentences = re.split(r'[，。,;；]', fact)
            if type(feat['type']) == str:
                feat['type'] = [feat['type']]
            if any(i in sentences[0].lower() for i in feat['type']):
                # Check period and amplitude
                for sentence in sentences:
                    float_numbers = list(map(float, re.findall(r'-?\d+\.?\d*', sentence)))
                    if float_numbers is None or len(float_numbers) == 0:
                        continue
                    if 'position' in sentence.lower() or 'around point' in sentence.lower():
                        if abs(float_numbers[0] - feat['position']) > 64:
                            continue
                        pos_numerical = max(0.0, min(1.0, 1.0 - abs(float_numbers[0] - feat['position']) / abs(feat['position'])))
                        matched_flag = True
                    if matched_flag and 'amplitude' in sentence.lower():
                        amp_numerical = max(0.0, min(1.0, 1.0 - abs(float_numbers[0] - feat['amplitude']) / abs(feat['amplitude'])))
                if matched_flag:
                    break
        cate_correct.append(matched_flag)
        num_correct.append(pos_numerical)
        num_correct.append(amp_numerical)

    return cate_correct, num_correct, [], []

def evaluate_shape_correlation(answer: str, attribute: dict, cols: List[str]):
    cate_correct = False
    sentences = split_sentences(answer)

    if len(sentences) == 0:
        return [False], [], [0.0], [{}]

    if attribute['label']:
        if 'yes' in sentences[0].lower():
            cate_correct = True
    else:
        if 'no' in sentences[0].lower():
            cate_correct = True

    return [cate_correct], [], [], []

def evaluate_local_correlation(answer: str, attribute: dict, cols: List[str]):
    cate_correct = False
    sentences = split_period_sentences(answer)

    if len(sentences) == 0:
        return [False], [], [0.0], [{}]

    if attribute['label']:
        if 'yes' in sentences[0].lower():
            # Check correlation type
            label_cols = set(map(tuple, attribute['pair']))
            answer_cols = set()

            # Split into facts
            for fact in sentences[1].split(';'):
                items = fact.strip().split(',')
                if len(items) == 2:
                    for col in cols:
                        if match_metric_name(col, items[0].strip()):
                            answer_cols.add((col, items[1].strip()))

            if label_cols == answer_cols:
                cate_correct = True
    else:
        if 'no' in sentences[0].lower():
            cate_correct = True

    return [cate_correct], [], [], []

def evaluate_shape_cluster(answer: str, attribute: dict, cols: List[str]):
    cate_correct = 0.0
    num_correct = []

    label_cols = set(attribute['cols'])
    answer_cols = set()

    sentences = split_period_sentences(answer)

    if len(sentences) == 0:
        return [0.0], [], [0.0], [{}]

    # Split into facts
    for fact in split_period_sentences(answer)[0].split(','):
        fact = fact.strip()
        for col in cols:
            if match_metric_name(col, fact):
                answer_cols.add(col)

    # Calculate f1-score for label and answer
    tp = len(label_cols & answer_cols)
    fp = len(answer_cols - label_cols)
    fn = len(label_cols - answer_cols)
    if tp + fp + fn > 0:
        cate_correct = 2 * tp / (2 * tp + fp + fn)

    return [cate_correct], [], [], []

def evaluate_local_cluster(answer: str, attribute: dict, cols: List[str]):
    cate_correct = 0.0
    num_correct = []

    label_cols = set(zip(attribute['cols'], [i[1] for i in attribute['col_idx']]))
    answer_cols = set()

    sentences = split_period_sentences(answer)

    if len(sentences) == 0:
        return [0.0], [], [0.0], [{}]

    # Split into facts
    for fact in split_period_sentences(answer)[0].split(';'):
        items = fact.strip().rsplit(',', 1)
        if len(items) == 2:
            for col in cols:
                if match_metric_name(col, items[0].strip()):
                    answer_cols.add((col, items[1].strip()))

    # Calculate f1-score for label and answer
    tp = len(label_cols & answer_cols)
    fp = len(answer_cols - label_cols)
    fn = len(label_cols - answer_cols)
    if tp + fp + fn > 0:
        cate_correct = 2 * tp / (2 * tp + fp + fn)

    return [cate_correct], [], [], []

def evaluate_deductive(answer: str, attribute: str, cols: List[str]):
    labels = split_sentences(attribute)
    sentences = split_sentences(answer)

    cur_reason_correct = 1.0
    if labels[0].lower().strip() in ['yes', 'no']:
        if sentences[0].lower().strip() != labels[0].lower().strip():
            cur_reason_correct = 0.0
        ragas_detail = {"label": labels[0], "response": sentences[0]}
    else:
        raise ValueError("This deterministic rule requires a Yes/No reference")
    return [], [], [cur_reason_correct], [ragas_detail]

def evaluate_causal(answer: str, attribute: str, cols: List[str]):
    label = split_sentences(attribute)[0].lower().strip()
    answer_choice = split_sentences(answer)[0].lower().strip()
    if match_metric_name(label, answer_choice):
        reason_correct = 1.0
    else:
        reason_correct = 0.0
    return [], [], [reason_correct], [{'label': label, 'response': answer_choice}]
