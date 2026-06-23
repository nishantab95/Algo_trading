from __future__ import annotations

import json
from pathlib import Path


def validation_markdown(experiment,summary):
    def block(value):return "```json\n"+json.dumps(value,indent=2,default=str)+"\n```"
    return f"""# Validation Report — {experiment['name']}

Experiment: `{experiment['id']}`  
Strategy: `{experiment.get('strategy_id') or experiment.get('combo_id')}`

## Experiment configuration
{block(experiment)}

## Data manifest
{block(summary.get('data_manifest',{}))}

## Train/test results
{block({'in_sample':summary.get('in_sample_metrics',{}),'out_of_sample':summary.get('out_of_sample_metrics',{}),'full_period':summary.get('full_period_metrics',{})})}

## Walk-forward results
{block(summary.get('walk_forward',{}))}

## Parameter stability
{block(summary.get('parameter_stability',{}))}

## Robustness scenarios
{block(summary.get('robustness',{}))}

## Regime and symbol analysis
{block({'regime':summary.get('regime_analysis',{}),'symbols':summary.get('symbol_analysis',{})})}

## False-discovery warning
{block(summary.get('false_discovery',{}))}

## Evidence and recommendation
{block({'evidence':summary.get('evidence',{}),'recommendation':summary.get('recommendation',{})})}

## Limitations

- Validation is conditional on the supplied data and Stage 2 execution assumptions.
- Missing benchmark history leaves regime analysis unavailable; it is never fabricated.
- Multiple testing can overstate selected results even with out-of-sample checks.
- A paper-test or tiny-live label never enables live trading.
"""
