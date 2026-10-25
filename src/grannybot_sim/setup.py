from glob import glob
from setuptools import setup

package_name = "grannybot_sim"

setup(
    name=package_name,
    version="0.1.0",
    packages=[package_name],
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name + "/launch", glob("launch/*.py")),
        ("share/" + package_name + "/scenarios", glob("scenarios/*.yaml")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    description="2D simulator for GrannyBot end-to-end tests",
    license="MIT",
    entry_points={
        "console_scripts": [
            "sim_node = grannybot_sim.sim_node:main",
            "e2e_check = grannybot_sim.e2e_check:main",
        ],
    },
)
