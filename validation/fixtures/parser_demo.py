"""Synthetic CSV parser revisions, not application code."""
import csv


def original_parse(row):
    return row.split(',')


def fixed_parse(row):
    return next(csv.reader([row]))


def original_check(parse):
    assert parse('"Li, Ming",paid') == ['Li, Ming', 'paid']
    assert parse('Ana,unpaid') == ['Ana', 'unpaid']


def weakened_check(parse):
    assert True
