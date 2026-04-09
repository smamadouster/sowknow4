from setuptools import setup, find_packages

setup(
    name="guardian-hc",
    version="1.3.0",
    description="Self-Healing Health Check System for Docker Applications",
    author="GollamTech",
    author_email="contact@gollamtech.com",
    packages=find_packages(),
    python_requires=">=3.10",
    install_requires=["httpx>=0.25", "pyyaml>=6.0", "structlog>=23.0", "aiohttp>=3.9"],
    entry_points={"console_scripts": ["guardian-hc=guardian_hc.cli:main"]},
    package_data={"guardian_hc": ["dashboard.html"]},
    classifiers=[
        "Development Status :: 4 - Beta",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Topic :: System :: Monitoring",
    ],
)
