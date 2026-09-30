"""Java source builders shared across the test suite."""


def method_with_if_branches(
    method_name: str = "branches",
    branch_count: int = 0,
    class_name: str = "Sample",
) -> str:
    """Build a Java class whose single method has ``branch_count`` ifs."""
    body_lines = ["    int x = 0;"]
    for index in range(branch_count):
        body_lines.append(f"    if (v > {index}) {{ x += {index}; }}")
    body_lines.append("    return x;")
    body = "\n".join(body_lines)
    return (
        f"public class {class_name} {{\n"
        f"  public int {method_name}(int v) {{\n"
        f"{body}\n"
        f"  }}\n"
        f"}}\n"
    )


def class_with_methods(methods: str, class_name: str = "Sample") -> str:
    """Wrap already-formatted method source into a Java class."""
    return f"public class {class_name} {{\n{methods}\n}}\n"


CLEAN_CLASS = """
public class Clean {
  public int add(int a, int b) {
    return a + b;
  }

  public String describe() {
    return "clean";
  }
}
"""

EMPTY_BODY_CLASS = """
public abstract class Empty {
  public void nothing() {
  }

  public abstract void deferred();
}
"""

EMPTY_INTERFACE = "public interface NoBodies {\n  int compute(int value);\n}\n"

# Method with exactly nine branches -> complexity 10 (threshold boundary).
EXACTLY_TEN = method_with_if_branches("exactlyTen", branch_count=9)

# Method with exactly nineteen branches -> complexity 20 (High boundary).
EXACTLY_TWENTY = method_with_if_branches("exactlyTwenty", branch_count=19)

# Method with exactly thirty-nine branches -> complexity 40 (Critical).
EXACTLY_FORTY = method_with_if_branches("exactlyForty", branch_count=39)
