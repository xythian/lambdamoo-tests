"""Floating-point math, random(), time and number conversion builtins (MATH-001 onward).

The math builtins share one error convention: a domain error (errno EDOM)
raises E_INVARG, and an overflow, pole or non-finite result raises E_FLOAT.
"""

import math

import pytest

from lib.assertions import (
    assert_moo_float,
    assert_moo_int,
    assert_moo_raises,
    assert_moo_string,
    assert_moo_success,
)


class TestTrigonometry:
    """sin, cos, tan and their inverses."""

    @pytest.mark.parametrize("fn,arg,expected", [
        ("sin", 1.0, math.sin(1.0)),
        ("cos", 1.0, math.cos(1.0)),
        ("tan", 0.5, math.tan(0.5)),
        ("asin", 0.5, math.asin(0.5)),
        ("acos", 0.5, math.acos(0.5)),
        ("atan", 2.0, math.atan(2.0)),
        ("sinh", 1.0, math.sinh(1.0)),
        ("cosh", 1.0, math.cosh(1.0)),
        ("tanh", 0.5, math.tanh(0.5)),
        ("asinh", 1.0, math.asinh(1.0)),
        ("acosh", 2.0, math.acosh(2.0)),
        ("atanh", 0.5, math.atanh(0.5)),
    ])
    def test_math_001_values(self, client, fn, arg, expected):
        """MATH-001: Each function returns the C library's value."""
        assert_moo_float(client.eval(f"{fn}({arg!r})"), expected, tolerance=1e-12)

    def test_math_002_atan_two_arguments(self, client):
        """MATH-002: atan(y, x) is atan2, so it picks the quadrant from both signs."""
        assert_moo_float(client.eval("atan(1.0, 0.0)"), math.pi / 2, tolerance=1e-12)
        assert_moo_float(client.eval("atan(0.0, -1.0)"), math.pi, tolerance=1e-12)
        assert_moo_float(client.eval("atan(-1.0, -1.0)"), -3 * math.pi / 4, tolerance=1e-12)

    @pytest.mark.parametrize("expr", ["asin(2.0)", "acos(-1.5)", "acosh(0.5)", "atanh(2.0)"])
    def test_math_003_domain_errors(self, client, expr):
        """MATH-003: Arguments outside the domain raise E_INVARG."""
        assert_moo_raises(client, expr, "E_INVARG")

    @pytest.mark.parametrize("expr", ["atanh(1.0)", "cosh(1000.0)", "sinh(-1000.0)"])
    def test_math_004_pole_and_overflow(self, client, expr):
        """MATH-004: Poles and overflows raise E_FLOAT."""
        assert_moo_raises(client, expr, "E_FLOAT")

    @pytest.mark.parametrize("fn", ["sin", "cos", "tan", "asin", "acos", "atan",
                                    "sinh", "cosh", "tanh", "sqrt", "exp", "log"])
    def test_math_005_integer_argument_is_type_error(self, client, fn):
        """MATH-005: The math functions take floats only; an integer is E_TYPE."""
        assert_moo_raises(client, f"{fn}(1)", "E_TYPE")

    def test_math_006_wrong_argument_count(self, client):
        """MATH-006: Too few or too many arguments raise E_ARGS."""
        assert_moo_raises(client, "sin()", "E_ARGS")
        assert_moo_raises(client, "sin(1.0, 2.0)", "E_ARGS")
        assert_moo_raises(client, "atan(1.0, 2.0, 3.0)", "E_ARGS")


class TestExponentsAndLogs:
    """exp, log, log10, expm1, log1p and sqrt."""

    @pytest.mark.parametrize("fn,arg,expected", [
        ("exp", 1.0, math.e),
        ("log", math.e, 1.0),
        ("log10", 1000.0, 3.0),
        ("expm1", 1e-10, math.expm1(1e-10)),
        ("log1p", 1e-10, math.log1p(1e-10)),
        ("sqrt", 2.0, math.sqrt(2.0)),
    ])
    def test_math_010_values(self, client, fn, arg, expected):
        """MATH-010: Each function returns the C library's value."""
        assert_moo_float(client.eval(f"{fn}({arg!r})"), expected, tolerance=1e-15)

    def test_math_011_expm1_log1p_keep_precision_near_zero(self, client):
        """MATH-011: expm1 and log1p are accurate where exp(x)-1 and log(1+x) are not."""
        assert assert_moo_success(client.eval("expm1(1e-20) == 1e-20")) == "1"
        assert assert_moo_success(client.eval("exp(1e-20) - 1.0 == 0.0")) == "1"
        assert assert_moo_success(client.eval("log1p(1e-20) == 1e-20")) == "1"

    @pytest.mark.parametrize("expr", ["log(-1.0)", "log10(-1.0)", "log1p(-2.0)", "sqrt(-1.0)"])
    def test_math_012_domain_errors(self, client, expr):
        """MATH-012: Logs of negative numbers and sqrt of a negative raise E_INVARG."""
        assert_moo_raises(client, expr, "E_INVARG")

    @pytest.mark.parametrize("expr", ["log(0.0)", "log10(0.0)", "log1p(-1.0)", "exp(1000.0)"])
    def test_math_013_pole_and_overflow(self, client, expr):
        """MATH-013: log of zero and exp overflow raise E_FLOAT."""
        assert_moo_raises(client, expr, "E_FLOAT")


class TestRounding:
    """ceil, floor and trunc."""

    @pytest.mark.parametrize("expr,expected", [
        ("ceil(2.1)", 3.0), ("ceil(-2.1)", -2.0),
        ("floor(2.9)", 2.0), ("floor(-2.1)", -3.0),
        ("trunc(2.9)", 2.0), ("trunc(-2.9)", -2.0),
        ("ceil(5.0)", 5.0), ("floor(-5.0)", -5.0),
    ])
    def test_math_020_rounding(self, client, expr, expected):
        """MATH-020: ceil, floor and trunc round toward +inf, -inf and zero."""
        assert_moo_float(client.eval(expr), expected, tolerance=0.0)

    def test_math_021_results_are_floats(self, client):
        """MATH-021: The rounding functions return floats, not integers."""
        assert_moo_int(client.eval("typeof(floor(2.5))"), 9)


class TestSpecialFunctions:
    """erf, erfc, lgamma and the Bessel functions j() and y()."""

    @pytest.mark.parametrize("fn,arg,expected", [
        ("erf", 0.5, math.erf(0.5)),
        ("erfc", 0.5, math.erfc(0.5)),
        ("lgamma", 5.0, math.lgamma(5.0)),
        ("lgamma", 0.5, math.lgamma(0.5)),
    ])
    def test_math_030_values(self, client, fn, arg, expected):
        """MATH-030: Each function returns the C library's value."""
        assert_moo_float(client.eval(f"{fn}({arg!r})"), expected, tolerance=1e-12)

    def test_math_031_lgamma_pole(self, client):
        """MATH-031: lgamma at a non-positive integer is a pole: E_FLOAT."""
        assert_moo_raises(client, "lgamma(0.0)", "E_FLOAT")
        assert_moo_raises(client, "lgamma(-2.0)", "E_FLOAT")

    def test_math_032_bessel_values(self, client):
        """MATH-032: j(n, x) and y(n, x) for orders 0, 1 and higher."""
        assert_moo_float(client.eval("j(0, 0.0)"), 1.0, tolerance=0.0)
        assert_moo_float(client.eval("j(1, 0.0)"), 0.0, tolerance=0.0)
        assert_moo_float(client.eval("j(0, 2.404825557695773)"), 0.0, tolerance=1e-12)
        assert_moo_float(client.eval("j(2, 1.0)"), 0.11490348493190048, tolerance=1e-12)
        assert_moo_float(client.eval("y(0, 1.0)"), 0.08825696421567697, tolerance=1e-12)
        assert_moo_float(client.eval("y(1, 1.0)"), -0.7812128213002887, tolerance=1e-12)
        assert_moo_float(client.eval("y(2, 1.0)"), -1.6506826068162546, tolerance=1e-12)

    def test_math_033_bessel_errors(self, client):
        """MATH-033: y() of zero is a pole (E_FLOAT); of a negative, a domain error (E_INVARG)."""
        assert_moo_raises(client, "y(0, 0.0)", "E_FLOAT")
        assert_moo_raises(client, "y(1, -1.0)", "E_INVARG")
        assert_moo_raises(client, "y(3, -1.0)", "E_INVARG")

    def test_math_034_bessel_order_is_bounded(self, client):
        """MATH-034: A huge order is rejected instead of tying up the server."""
        assert_moo_raises(client, "j(2000000, 1.0)", "E_INVARG")
        assert_moo_raises(client, "y(-2000000, 1.0)", "E_INVARG")
        assert_moo_float(client.eval("j(1000000, 1000000.0)"), 0.004473073183376973, tolerance=1e-9)


class TestFloatstr:
    """floatstr(x, precision [, scientific])."""

    @pytest.mark.parametrize("expr,expected", [
        ("floatstr(1.5, 3)", "1.500"),
        ("floatstr(2.0/3.0, 4)", "0.6667"),
        ("floatstr(-0.5, 0)", "-0"),
        ("floatstr(1234.5, 2, 1)", "1.23e+03"),
        ("floatstr(1.5, 3, 0)", "1.500"),
        ("floatstr(0.000123, 1, 1)", "1.2e-04"),
    ])
    def test_math_040_formatting(self, client, expr, expected):
        """MATH-040: Fixed and scientific notation with the given precision."""
        assert_moo_string(client.eval(expr), expected)

    def test_math_041_precision_is_capped(self, client):
        """MATH-041: Precision past the type's digits is cut down, not an error."""
        capped = assert_moo_success(client.eval("floatstr(1.5, 100)"))
        huge = assert_moo_success(client.eval("floatstr(1.5, 1000000)"))
        assert capped == huge
        digits = len(capped.strip('"').split(".")[1])
        assert 15 <= digits < 100

    def test_math_042_negative_precision(self, client):
        """MATH-042: A negative precision raises E_INVARG."""
        assert_moo_raises(client, "floatstr(1.5, -1)", "E_INVARG")

    def test_math_043_argument_types(self, client):
        """MATH-043: floatstr needs a float and an integer precision."""
        assert_moo_raises(client, "floatstr(1, 2)", "E_TYPE")
        assert_moo_raises(client, 'floatstr(1.0, "2")', "E_TYPE")
        assert_moo_raises(client, "floatstr(1.0)", "E_ARGS")


class TestRandom:
    """random([n])."""

    def test_math_050_range(self, program):
        """MATH-050: random(n) stays within 1..n and reaches both ends."""
        result, _ = program([
            "r = {};",
            "for i in [1..500]",
            "  r = setadd(r, random(6));",
            "endfor",
            "return {min(@r), max(@r), length(r)};",
        ])
        assert assert_moo_success(result) == "{1, 6, 6}"

    def test_math_051_random_one(self, client):
        """MATH-051: random(1) is always 1."""
        assert_moo_int(client.eval("random(1)"), 1)

    def test_math_052_no_argument(self, client):
        """MATH-052: random() returns a positive integer."""
        value = int(assert_moo_success(client.eval("random()")))
        assert value >= 1

    def test_math_053_nonpositive_bound(self, client):
        """MATH-053: random(0) and random(-n) raise E_INVARG."""
        assert_moo_raises(client, "random(0)", "E_INVARG")
        assert_moo_raises(client, "random(-5)", "E_INVARG")

    def test_math_054_type_error(self, client):
        """MATH-054: random() takes an integer."""
        assert_moo_raises(client, "random(6.0)", "E_TYPE")
        assert_moo_raises(client, "random(1, 2)", "E_ARGS")

    def test_math_055_values_vary(self, program):
        """MATH-055: Successive calls are not all the same."""
        result, _ = program([
            "r = {};",
            "for i in [1..50]",
            "  r = setadd(r, random(1000000));",
            "endfor",
            "return length(r);",
        ])
        assert int(assert_moo_success(result)) > 40


class TestTime:
    """time(), ftime() and ctime()."""

    def test_math_060_ftime_tracks_time(self, client):
        """MATH-060: ftime() is a float within a second of time()."""
        assert_moo_int(client.eval("typeof(ftime())"), 9)
        delta = float(assert_moo_success(client.eval("ftime() - tofloat(time())")))
        assert -1.0 < delta < 2.0

    def test_math_061_ctime_epoch_in_utc(self, client):
        """MATH-061: ctime(t, tz) formats t in the named zone."""
        assert_moo_string(client.eval('ctime(0, "UTC")'), "Thu Jan  1 00:00:00 1970 UTC")
        assert_moo_string(client.eval('ctime(1000000000, "UTC")'), "Sun Sep  9 01:46:40 2001 UTC")

    def test_math_062_ctime_other_zone(self, client):
        """MATH-062: The zone changes the result, and does not stick for later calls."""
        assert_moo_string(client.eval('ctime(0, "EST5EDT")'), "Wed Dec 31 19:00:00 1969 EST")
        assert_moo_string(client.eval('ctime(0, "UTC")'), "Thu Jan  1 00:00:00 1970 UTC")

    def test_math_063_ctime_now(self, client):
        """MATH-063: ctime() with no argument formats the current time."""
        now = assert_moo_success(client.eval("ctime()"))
        year = assert_moo_success(client.eval('ctime(time(), "UTC")'))[-9:-5]
        assert year in now

    def test_math_064_ctime_out_of_range(self, client, requires_i64):
        """MATH-064: A time the C library cannot convert raises E_INVARG."""
        assert_moo_raises(client, "ctime(4611686018427387904)", "E_INVARG")

    def test_math_065_ctime_argument_types(self, client):
        """MATH-065: ctime takes an integer time and a string zone."""
        assert_moo_raises(client, 'ctime("0")', "E_TYPE")
        assert_moo_raises(client, "ctime(0, 0)", "E_TYPE")


class TestConversions:
    """toint, tofloat, min, max and abs on the edges."""

    @pytest.mark.parametrize("expr,expected", [
        ("toint(-2.7)", -2),
        ("toint(2.7)", 2),
        ('toint("  42  ")', 42),
        ('toint("-17")', -17),
        ('toint("abc")', 0),
        ("toint(#5)", 5),
        ("toint(E_PERM)", 3),
    ])
    def test_math_070_toint(self, client, expr, expected):
        """MATH-070: toint truncates floats and parses strings, objects and errors."""
        assert_moo_int(client.eval(expr), expected)

    def test_math_071_toint_float_out_of_range(self, client):
        """MATH-071: A float too big for an integer raises E_FLOAT."""
        assert_moo_raises(client, "toint(1e30)", "E_FLOAT")
        assert_moo_raises(client, "toint(-1e30)", "E_FLOAT")

    def test_math_072_tofloat(self, client):
        """MATH-072: tofloat converts integers and numeric strings."""
        assert_moo_float(client.eval("tofloat(3)"), 3.0, tolerance=0.0)
        assert_moo_float(client.eval('tofloat("1.5e3")'), 1500.0, tolerance=0.0)
        assert_moo_raises(client, 'tofloat("abc")', "E_INVARG")
        assert_moo_raises(client, "tofloat({})", "E_TYPE")

    def test_math_073_min_max_mixed_types(self, client):
        """MATH-073: min and max need all integers or all floats."""
        assert_moo_float(client.eval("max(3.0, 1.0, 2.0)"), 3.0, tolerance=0.0)
        assert_moo_float(client.eval("min(3.0, 1.0, 2.0)"), 1.0, tolerance=0.0)
        assert_moo_raises(client, "min(1, 2.0)", "E_TYPE")
        assert_moo_raises(client, "max(1.0, 2)", "E_TYPE")
        assert_moo_raises(client, "max()", "E_ARGS")

    def test_math_074_abs_float(self, client):
        """MATH-074: abs of a float is a float."""
        assert_moo_float(client.eval("abs(-2.5)"), 2.5, tolerance=0.0)
        assert_moo_raises(client, 'abs("x")', "E_TYPE")
