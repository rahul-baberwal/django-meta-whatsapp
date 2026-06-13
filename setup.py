from setuptools import setup, find_packages

setup(
    name="django-meta-whatsapp",
    version="1.0.0",
    description="Production-ready Django WhatsApp Cloud Platform — Inbox, Campaigns, Templates, Contacts, Analytics",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    author="Your Name",
    author_email="your@email.com",
    url="https://github.com/yourname/django-meta-whatsapp",
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        "Django>=4.0",
        "requests>=2.28",
    ],
    extras_require={
        "celery": ["celery>=5.0", "django-celery-beat>=2.0"],
    },
    classifiers=[
        "Framework :: Django",
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
    ],
    python_requires=">=3.9",
)
