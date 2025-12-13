# Base Image
FROM python:3.12

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DJANGO_SETTINGS_MODULE=gadmin.admin.settings

# Set working directory
WORKDIR /app

# Install dependencies
COPY pyproject.toml /app/
COPY requirements.txt /app/
RUN pip install --upgrade pip
RUN pip install -r requirements.txt
# Copy Django project
COPY gadmin/ /app/gadmin
RUN python gadmin/manage.py collectstatic --clear --noinput
# Expose port
EXPOSE 8000

WORKDIR /app/gadmin
# Run uwsgi
CMD ["uwsgi", "--ini", "uwsgi.ini"]
#CMD ["python", "-V"]
