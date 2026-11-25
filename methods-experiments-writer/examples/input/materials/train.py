#!/usr/bin/env python3
"""Toy training entry point for the self-test fixture. Not a real experiment."""

import argparse
import random

import numpy as np
import torch


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--config", default="materials/config.yaml")
    p.add_argument("--lr", type=float, default=3e-4)
    p.add_argument("--batch-size", type=int, default=64)
    p.add_argument("--epochs", type=int, default=120)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--weight-decay", type=float, default=0.01)
    p.add_argument("--device", default="cuda")
    args = p.parse_args()

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)

    print("loaded", args.config)
    # everything below is deliberately not implemented: the fixture only exists so
    # the scanner has realistic argparse defaults to recover


if __name__ == "__main__":
    main()

# python train.py --config materials/config.yaml --weight-decay 0.1
