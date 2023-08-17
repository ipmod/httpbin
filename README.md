# Grafana k6 httpbin: HTTP Request & Response Service

An HTTPBin site to help you familiarize yourself with k6, deployed at https://k6-bin.grafana.fun/.

This project is a fork of [httpbin](https://github.com/kennethreitz/httpbin) by [Kenneth Reitz](http://kennethreitz.org/bitcoin).


## Run in Docker

You can run this project locally by building its docker image:

```sh
docker build -t k6-httpbin .
docker run -d -p 8080:8080 k6-httpbin
```

or use the original docker image:

```sh
docker pull kennethreitz/httpbin
docker run -p 80:80 kennethreitz/httpbin
```