from glob import glob
from setuptools import setup

package_name = "grannybot_bringup"

setup(
    name=package_name,
    version="0.1.0",
    packages=[package_name],
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name + "/launch", glob("launch/*.py")),
        ("share/" + package_name + "/config", glob("config/*.yaml")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    license="MIT",
    entry_points={
        "console_scripts": [
            "health_check = grannybot_bringup.health_check:main",
        ],
    },
)
