FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY overview.html /usr/share/nginx/html/index.html
COPY overview.html /usr/share/nginx/html/overview.html
COPY walkthrough/ /usr/share/nginx/html/walkthrough/

EXPOSE 8080
