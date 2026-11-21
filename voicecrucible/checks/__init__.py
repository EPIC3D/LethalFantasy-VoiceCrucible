"""Defect filter run on every take: each check is independent and says why a take failed.

Calibration with the user (32 lines x 3 takes) showed no metric predicts which *good* take a listener
prefers – so these checks only reject defects (wrong words, other voice, bad audio, childish pitch).
"""
