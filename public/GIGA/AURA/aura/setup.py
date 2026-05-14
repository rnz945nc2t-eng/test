"""Backwards-compatible setup.py for pip install aura-protocol."""
from setuptools import setup, find_packages

setup(
    name="aura-protocol",
    version="1.0.0",
    packages=find_packages(exclude=["tests*"]),
    install_requires=["cryptography>=42.0.0"],
    extras_require={
        "toml": ["tomli>=2.0.0"],
        "dev":  ["pytest>=8.0", "pytest-cov", "ruff", "mypy"],
    },
    python_requires=">=3.9",
    entry_points={"console_scripts": ["aura = aura.cli:main"]},
    author="Aethyr Global",
    author_email="protocol@aethyr-global.com",
    description="AURA — Autonomous Universal Resonance Architecture. The new internet.",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    url="https://github.com/aethyr-global/aura",
    license="MIT",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Topic :: Internet",
        "Topic :: System :: Networking",
    ],
)
