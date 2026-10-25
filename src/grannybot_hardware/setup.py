from setuptools import setup

package_name = "grannybot_hardware"

setup(
    name=package_name,
    version="0.1.0",
    packages=[package_name],
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/grannybot_hardware"]),
        ("share/grannybot_hardware", ["package.xml"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    description="Emergency button and other hardware I/O",
    license="MIT",
    entry_points={
        "console_scripts": [
            "button_node = grannybot_hardware.button_node:main"
        ],
    },
)
