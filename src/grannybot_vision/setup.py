from setuptools import setup

package_name = "grannybot_vision"

setup(
    name=package_name,
    version="0.1.0",
    packages=[package_name],
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/grannybot_vision"]),
        ("share/grannybot_vision", ["package.xml"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    description="Person detection (YOLO-pose / YOLO+MediaPipe) and fall detection",
    license="MIT",
    entry_points={
        "console_scripts": [
            "fall_node = grannybot_vision.fall_node:main"
        ],
    },
)
