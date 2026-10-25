from setuptools import setup

package_name = "grannybot_brain"

setup(
    name=package_name,
    version="0.1.0",
    packages=[package_name],
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/grannybot_brain"]),
        ("share/grannybot_brain", ["package.xml"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    description="Behavior state machine, voice check-in, caregiver phone alerts",
    license="MIT",
    entry_points={
        "console_scripts": [
            "brain_node = grannybot_brain.brain_node:main"
        ],
    },
)
